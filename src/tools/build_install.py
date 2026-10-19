#!/usr/bin/env python3
# coding: utf-8
r"""src/tools/build_install.py — 构建与安装窗口

一个窗口完成四件事：

1. 勾选要构建的语言（可多选），点「构建」，逐个编译并显示进度；
2. 选游戏目录（须含 PR2.exe）；
3. 把构建产物复制进去；
4. 点「运行游戏」用注入器启动器把游戏拉起来。

PR2.exe 全程不被修改。装好之后用装到游戏目录里的
PR2Launcher.exe 启动游戏，语言包在启动时读取，
所以改完翻译只要重新构建 + 重新安装。

单独运行本脚本时它只做安装；构建由 src\build_n_patch.bat
在编译完注入器后调用，届时 --build 会一并把语言包编出来。
"""

import ctypes
import hashlib
import os
import queue
import shutil
import subprocess
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    # 并非所有 Python 都带 tkinter。直接告诉用户手工复制哪些文件，
    # 而不是抛一段 traceback。
    sys.stderr.write(
        "[patch] This Python has no tkinter, so the window cannot open.\n"
        "[patch] Copy these into your Port Royale 2 folder by hand:\n"
        "[patch]   PR2Launcher.exe\n"
        "[patch]   PR2TextSource.dll\n"
        "[patch]   PR2Packs\\\n"
    )
    sys.exit(2)


HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
BUILD = os.path.join(ROOT, "build")
PACK_OUT = os.path.join(BUILD, "PR2Packs")
LOCALE_INI = os.path.join(SRC, "locale.ini")

# 直接复制进游戏目录的文件。
FLAT_FILES = ("PR2Launcher.exe", "PR2TextSource.dll")
# 整个目录一起复制。
PACK_DIR = "PR2Packs"
GAME_EXE = "PR2.exe"
#: 装好之后用它启动游戏。它挂起 PR2.exe、注入 DLL、再恢复执行。
LAUNCHER = "PR2Launcher.exe"


# ------------------------------------------------------------ 可用语言

def available_langs():
    r"""src\translations\ 下可编辑的语言代码，供勾选。

    规则只有一份，在 translate.py 里（文件名即语言代码，
    `_` 开头的不是语言）；这里直接问它，避免两处各扫一遍而漂移。
    """
    sys.path.insert(0, HERE)
    import translate as T
    return T.target_langs()


# ------------------------------------------------------------ 构建产物

def missing_outputs(need_pack=True):
    """部署前必须存在的构建产物。"""
    missing = [n for n in FLAT_FILES if not os.path.isfile(os.path.join(BUILD, n))]
    if need_pack:
        if not os.path.isdir(PACK_OUT):
            missing.append(PACK_DIR + "\\")
    return missing


def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, GAME_EXE))


def writable(path):
    """游戏在运行时旧 DLL 与启动器都被占着，复制会以共享冲突失败，
    不是权限不足。先探一下写权限，好在报错时说清是哪一种。"""
    probe = os.path.join(path, ".pr2loc_write_test")
    try:
        with open(probe, "wb"):
            pass
        os.remove(probe)
    except OSError:
        return False
    return True


def same_content(a, b):
    """两个文件内容是否一致。

    比大小先过一遍：语言包几百 KB，同尺寸却不同的机会极少，
    而逐字节比只在尺寸相同时才做。
    """
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    return file_digest(a) == file_digest(b)


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def deploy_steps(target, langs):
    """列出安装要做的事，供进度条按步推进。

    langs 给出时只复制这些语言的语言包 —— build\\PR2Packs 是累积
    目录，里面可能还留着上一次构建的其他语言，整目录照搬会把
    locale.ini 根本没指向的语言也塞进游戏。langs 为 None 时整目录复制。
    """
    steps = [(n, os.path.join(BUILD, n), os.path.join(target, n))
             for n in FLAT_FILES]
    steps.append(("%s\\" % PACK_DIR, None, os.path.join(target, PACK_DIR)))
    wanted = ["locale.ini"]
    if langs:
        wanted += ["%s.txt" % c for c in langs]
    for name in wanted:
        src = os.path.join(PACK_OUT, name)
        if os.path.isfile(src):
            steps.append(("%s\\%s" % (PACK_DIR, name), src,
                          os.path.join(target, PACK_DIR, name)))
    return steps


def copy_if_different(src, dst):
    """内容不同才复制。返回 "copied" / "same" / "failed"。

    已经一致就不动目标文件：反复点安装时 DLL 与启动器不会被
    反复改写，而正在运行的游戏加载着旧 DLL，跳过也能避免
    撞上文件占用。
    """
    if os.path.isfile(dst) and same_content(src, dst):
        return "same"
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return "copied"
    except OSError:
        return "failed"


def prune_stale_pack(target, langs):
    """删掉游戏目录 PR2Packs\\ 里本次不装的文件，返回删掉的名字。

    只删多出来的，不动要留的 —— 整个 rmtree 会让「内容相同就跳过」
    永远生效不了，语言包每次都被重写。
    """
    dst_pack = os.path.join(target, PACK_DIR)
    if not os.path.isdir(dst_pack):
        return []
    keep = {"locale.ini"}
    if langs:
        keep |= {"%s.txt" % c for c in langs}
    removed = []
    for name in os.listdir(dst_pack):
        if name in keep:
            continue
        p = os.path.join(dst_pack, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed.append(name)
        except OSError:
            pass
    return removed


def deploy(target, langs=None):
    """把构建产物复制到 target。返回 (是否成功, 说明)。"""
    if not writable(target):
        return False, (
            "无法写入该目录。\n\n"
            "最常见的原因是游戏正在运行 —— 请先关闭 Port Royale 2 再试。"
        )
    copied, same, failed = [], [], []
    try:
        for name in prune_stale_pack(target, langs):
            same.append("%s（已移除）" % name)

        for label, src, dst in deploy_steps(target, langs):
            if src is None:                        # 目录本身
                os.makedirs(dst, exist_ok=True)
                continue
            r = copy_if_different(src, dst)
            name = os.path.basename(dst)
            (copied if r == "copied" else same if r == "same" else failed).append(name)

    except PermissionError:
        return False, "权限不足。请确认游戏已关闭，且该目录允许写入。"
    except OSError as exc:
        return False, "复制失败：%s" % exc

    if failed:
        return False, "以下文件复制失败：%s\n\n请确认游戏已关闭。" % "、".join(failed)
    return True, (
        "已安装到：\n%s\n\n"
        "新复制：%s\n未改动：%s\n\n"
        "点「运行游戏」即可启动，或以后手动运行这个目录下的\n"
        "%s。语言包在游戏启动时读取，改完翻译重新构建再安装一次即可。"
        % (target,
           "、".join(copied) or "（无）",
           "、".join(same) or "（无）",
           LAUNCHER)
    )


def run_deploy(target, langs, events):
    """安装线程主体，逐步推进进度条。任何一步失败就停下。"""
    try:
        if not writable(target):
            events.put(("line", "无法写入该目录。"))
            events.put(("line", "最常见的原因是游戏正在运行 —— 请先关闭游戏再试。"))
            events.put(("deploy_failed", ""))
            return

        for name in prune_stale_pack(target, langs):
            events.put(("line", "移除 %s\\%s（本次不装）" % (PACK_DIR, name)))

        steps = deploy_steps(target, langs)
        for i, (label, src, dst) in enumerate(steps, 1):
            events.put(("deploy_step", (i, len(steps), label)))
            if src is None:
                os.makedirs(dst, exist_ok=True)
                events.put(("line", "  新建 %s" % label))
                continue

            r = copy_if_different(src, dst)
            if r == "same":
                events.put(("line", "  跳过 %s（内容相同）" % label))
            elif r == "copied":
                events.put(("line", "  已复制 %s" % label))
            else:
                events.put(("line", "  复制失败 %s —— 游戏可能正在运行" % label))
                events.put(("deploy_failed", ""))
                return

        events.put(("deploy_ok", target))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "安装出错：%s" % exc))
        events.put(("deploy_failed", ""))


def launcher_installed(target):
    return os.path.isfile(os.path.join(target, LAUNCHER))


def launch_game(target):
    """用注入器启动器把游戏拉起来（带汉化）。返回 (是否成功, 说明)。

    启动器自己会 CreateProcess 一个挂起的 PR2.exe、注入 DLL 再恢复，
    所以它很快就会退出 —— 不用等它结束。控制台留给它自己开，
    那里会打印注入结果，窗口不该抢。

    工作目录必须设成游戏目录：启动器给 CreateProcess 传的
    lpCurrentDirectory 是 NULL，PR2.exe 会继承启动器的 cwd，
    而它按相对路径找资源文件。
    """
    exe = os.path.join(target, LAUNCHER)
    if not os.path.isfile(exe):
        return False, "该目录下没有 %s，请先安装。" % LAUNCHER
    if not is_game_dir(target):
        return False, "该目录下没有 %s，请重新选择游戏目录。" % GAME_EXE
    try:
        subprocess.Popen([exe], cwd=target, close_fds=True)
    except OSError as exc:
        return False, "启动失败：%s" % exc
    return True, "已通过 %s 启动游戏。" % LAUNCHER


def launch_vanilla(target):
    """直接启动原版 PR2.exe，不注入任何东西。返回 (是否成功, 说明)。

    用来对比：同一个界面到底有没有变汉化。游戏按相对路径读资源，
    所以 cwd 必须是游戏目录。
    """
    if not is_game_dir(target):
        return False, "该目录下没有 %s，请重新选择游戏目录。" % GAME_EXE
    try:
        subprocess.Popen([os.path.join(target, GAME_EXE)], cwd=target,
                         close_fds=True)
    except OSError as exc:
        return False, "启动失败：%s" % exc
    return True, "已直接启动 %s（未注入，不含汉化）。" % GAME_EXE


# ------------------------------------------------------------ 构建

def build_pack(lang, out_dir, events):
    """在子进程里跑 compile_pack.py，把输出送到事件队列。

    不直接 import 它：那个脚本会做 import-time 的路径推导，而且
    它的 stdout 是给命令行看的，逐行读回来反而更可控 —— 失败时
    整个 stderr 都能显示出来。

    脚本自己已经在「编不出条目」时报错退出码 1 且不写文件了。
    这里仍查一次条目数兜底：空包装进游戏等于没汉化，而 GUI 是
    会把它复制过去的最后一道关口。
    """
    script = os.path.join(HERE, "compile_pack.py")
    cmd = [sys.executable, script, "--lang", lang, "--out", out_dir]
    events.put(("line", "[%s] 编译中…" % lang))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, encoding="utf-8", errors="replace",
    )
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            events.put(("line", line))
    code = proc.wait()

    pack = os.path.join(out_dir, "%s.txt" % lang)
    if code == 0:
        entries = count_entries(pack)
        if entries == 0:
            events.put(("line", "[%s] 失败：%s 一条译文都没有，已拦下。"
                        % (lang, pack)))
            try:
                os.remove(pack)
            except OSError:
                pass
            code = 1
        else:
            events.put(("line", "[%s] 完成，%d 条，%s.txt（%d 字节）"
                        % (lang, entries, lang, os.path.getsize(pack))))
    else:
        events.put(("line", "[%s] 失败，退出码 %d" % (lang, code)))
    events.put(("lang_done", (lang, code)))
    return code


def count_entries(pack_path):
    """语言包里的条目数。首行是文件头注释，不算条目。"""
    if not os.path.isfile(pack_path):
        return 0
    n = 0
    with open(pack_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def run_build(langs, events):
    """构建线程主体。语言逐个编译，任何一个失败就停下。"""
    try:
        if not langs:
            events.put(("line", "没有勾选任何语言。"))
            events.put(("build_failed", ""))
            return

        os.makedirs(PACK_OUT, exist_ok=True)

        for lang in langs:
            events.put(("lang_start", lang))
            code = build_pack(lang, PACK_OUT, events)
            if code != 0:
                events.put(("build_failed", lang))
                return

        # locale.ini 决定 DLL 读哪个语言包，是一份模板而非生成物。
        if not os.path.isfile(LOCALE_INI):
            events.put(("line", "缺少 %s，无法生成 PR2Packs\\locale.ini"
                        % LOCALE_INI))
            events.put(("build_failed", ""))
            return
        shutil.copy2(LOCALE_INI, os.path.join(PACK_OUT, "locale.ini"))
        events.put(("line", "已复制 locale.ini"))
        events.put(("build_ok", list(langs)))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "构建出错：%s" % exc))
        events.put(("build_failed", ""))


# ------------------------------------------------------------ 界面

class App(tk.Tk):
    POLL_MS = 80
    #: 构建结束后按钮还要多锁一会儿。构建常常不到一秒，禁用状态
    #: 一闪而过，用户会以为没生效而连点；这段时间里重复构建
    #: 也确实没有意义（产物一样）。
    BUILD_COOLDOWN_MS = 1200

    def __init__(self, do_build):
        super().__init__()
        self.title("Port Royale 2 汉化 —— 构建与安装")
        self.resizable(False, False)

        self.events = queue.Queue()
        self.worker = None
        self.built_langs = []
        self.total = 0
        self.done = 0
        self.building = False
        self.installing = False
        self.installed = False
        self.build_cool = 0
        self.missing_injector = missing_outputs(need_pack=False)

        self.var_dir = tk.StringVar()
        self.status = tk.StringVar()

        langs = available_langs()
        self.vars = {}
        for code in langs:
            v = tk.BooleanVar(value=True)
            self.vars[code] = v

        self._build_ui(langs, do_build)
        self._sync()
        self._center()
        self.after(self.POLL_MS, self._poll)

    # ---- 布局

    def _build_ui(self, langs, do_build):
        frm = tk.Frame(self, padx=14, pady=10)
        frm.grid(row=0, column=0, sticky="nsew")

        # -- 语言
        tk.Label(frm, text="要构建的语言（可多选）").grid(
            row=0, column=0, columnspan=2, sticky="w")

        listbox = tk.Frame(frm)
        listbox.grid(row=1, column=0, sticky="w", pady=(4, 0))
        if langs:
            for code in langs:
                tk.Checkbutton(
                    listbox, text=code, variable=self.vars[code],
                    command=self._sync,
                ).pack(anchor="w")
        else:
            tk.Label(
                listbox, text="（src\\translations\\ 下没有可构建的语言）",
                fg="#a00000",
            ).pack(anchor="w")

        self.btn_build = tk.Button(
            frm, text="构建所选语言", command=self.on_build, width=18)
        self.btn_build.grid(row=1, column=1, sticky="ne", padx=(14, 0), pady=(4, 0))

        # -- 进度
        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=1.0)
        self.bar.grid(row=2, column=0, columnspan=2, sticky="we", pady=(10, 2))
        self.lbl_status = tk.Label(
            frm, textvariable=self.status, anchor="w", justify="left")
        self.lbl_status.grid(row=3, column=0, columnspan=2, sticky="we")

        self.log = tk.Text(frm, height=7, width=58, state="disabled",
                           wrap="word", bg="#f4f4f4")
        self.log.grid(row=4, column=0, columnspan=2, sticky="we", pady=(6, 0))

        # -- 游戏目录
        tk.Label(frm, text="游戏目录（须含 %s）" % GAME_EXE).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        dir_row = tk.Frame(frm)
        dir_row.grid(row=6, column=0, columnspan=2, sticky="we", pady=(4, 0))
        tk.Entry(dir_row, textvariable=self.var_dir, width=46,
                 state="readonly").pack(side="left", fill="x", expand=True)
        tk.Button(dir_row, text="浏览…", width=8,
                  command=self.on_browse).pack(side="left", padx=(6, 0))

        # -- 按钮
        btns = tk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))
        tk.Button(btns, text="关闭", width=10, command=self.destroy).pack(side="right")
        self.btn_play = tk.Button(btns, text="运行游戏", width=10,
                                  command=self.on_play)
        self.btn_play.pack(side="right", padx=(0, 6))
        self.btn_vanilla = tk.Button(btns, text="原版启动", width=10,
                                     command=self.on_vanilla)
        self.btn_vanilla.pack(side="right", padx=(0, 6))
        self.btn_install = tk.Button(btns, text="安装", width=10,
                                     command=self.on_install)
        self.btn_install.pack(side="right", padx=(0, 6))

        frm.columnconfigure(0, weight=1)

        if self.missing_injector:
            self.status.set("注入器未构建，缺少：%s"
                            % "、".join(self.missing_injector))
        else:
            self.status.set("就绪")

        if do_build:
            self.after(120, self.on_build)

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))

    # ---- 状态

    def selected_langs(self):
        return [c for c in sorted(self.vars) if self.vars[c].get()]

    def busy(self):
        return self.building or self.installing

    def end_build(self):
        """构建线程收尾：进冷却，之后才允许再点。

        冷却用 self.after 而不是 busy()：构建常常不到一秒，
        禁用态一闪而过，重复点击的意图却很清楚。
        """
        self.building = False
        self.build_cool = 1
        self.after(self.BUILD_COOLDOWN_MS, self._clear_cool)

    def _clear_cool(self):
        self.build_cool = 0
        self._sync()

    def ready_to_play(self):
        """与本次构建无关：游戏目录里已经装好启动器就能跑，
        不要求这次构建过语言包。"""
        d = self.var_dir.get()
        return (not self.busy()
                and is_game_dir(d)
                and launcher_installed(d))

    def ready_to_vanilla(self):
        d = self.var_dir.get()
        return not self.busy() and is_game_dir(d)

    def _sync(self):
        locked = self.busy()
        self.btn_install.configure(
            state="normal" if (not locked
                               and not self.missing_injector
                               and bool(self.built_langs)
                               and is_game_dir(self.var_dir.get()))
            else "disabled")
        self.btn_play.configure(
            state="normal" if self.ready_to_play() else "disabled")
        self.btn_vanilla.configure(
            state="normal" if self.ready_to_vanilla() else "disabled")
        self.btn_build.configure(
            state="disabled" if locked or self.build_cool or not self.vars
            else "normal")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---- 事件

    def on_build(self):
        if self.busy() or self.build_cool:
            return
        langs = self.selected_langs()
        if not langs:
            messagebox.showwarning("没有选择", "请至少勾选一种语言。")
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.built_langs = []
        self.bar.configure(value=0.0, maximum=float(len(langs)))
        self.total = len(langs)
        self.done = 0
        # 先置位再起线程：busy() 不再靠 is_alive()，否则构建太快时
        # 两次轮询之间就结束，按钮看起来一直可点，还能重复起线程。
        self.building = True
        self.status.set("正在构建 %s…" % "、".join(langs))
        self.worker = threading.Thread(
            target=run_build, args=(langs, self.events), daemon=True)
        self.worker.start()
        self._sync()

    def on_browse(self):
        chosen = filedialog.askdirectory(
            title="选择 Port Royale 2 的安装目录（需包含 %s）" % GAME_EXE,
            mustexist=True)
        if chosen:
            self.set_dir(chosen)

    def set_dir(self, path):
        path = os.path.normpath(path)
        self.var_dir.set(path)
        if not is_game_dir(path):
            self.status.set("该目录里没有 %s，请选游戏安装目录。" % GAME_EXE)
        elif launcher_installed(path):
            self.status.set("找到 %s，已安装过补丁。" % GAME_EXE)
        else:
            self.status.set("找到 %s，可以安装。" % GAME_EXE)
        self._sync()

    def on_install(self):
        if self.busy():
            return
        langs = list(self.built_langs)
        self.bar.configure(value=0.0)
        self.status.set("正在安装到 %s …" % self.var_dir.get())
        self.installing = True
        self.worker = threading.Thread(
            target=run_deploy,
            args=(self.var_dir.get(), langs, self.events), daemon=True)
        self.worker.start()
        self._sync()

    def on_play(self):
        ok, message = launch_game(self.var_dir.get())
        if ok:
            self.status.set(message)
        else:
            messagebox.showerror("无法启动", message)

    def on_vanilla(self):
        ok, message = launch_vanilla(self.var_dir.get())
        if ok:
            self.status.set(message)
        else:
            messagebox.showerror("无法启动", message)

    def on_close(self):
        # 构建与安装线程都是 daemon，窗口关掉时它们随进程一起结束。
        self.destroy()

    # ---- 队列泵

    def _poll(self):
        self._drain()
        self._sync()
        self.after(self.POLL_MS, self._poll)

    def _drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self._log(payload)

                elif kind == "lang_start":
                    self.status.set("正在构建 %s…" % payload)

                elif kind == "lang_done":
                    lang, code = payload
                    if code == 0:
                        self.done += 1
                        self.bar.configure(value=float(self.done))

                elif kind == "build_ok":
                    self.end_build()
                    self.built_langs = payload
                    left = missing_outputs()
                    if left:
                        self.status.set("构建结束，但缺少：%s" % "、".join(left))
                    elif is_game_dir(self.var_dir.get()):
                        self.status.set("构建完成，可以安装。")
                    else:
                        self.status.set("构建完成，请选择游戏目录。")

                elif kind == "build_failed":
                    self.end_build()
                    self.status.set("构建失败，没有复制任何文件。")
                    messagebox.showerror(
                        "构建失败", "详见下方日志。\n没有向游戏目录复制任何文件。")

                elif kind == "deploy_step":
                    i, n, label = payload
                    self.bar.configure(maximum=float(n), value=float(i - 1))
                    self.status.set("正在安装（%d/%d）：%s" % (i, n, label))

                elif kind == "deploy_ok":
                    self.installing = False
                    self.installed = True
                    self.bar.configure(value=float(self.bar["maximum"]))
                    self.status.set("安装完成，可以点「运行游戏」。")
                    self._sync()
                    messagebox.showinfo(
                        "安装完成",
                        "已安装到：\n%s\n\n现在可以点「运行游戏」启动汉化版，"
                        "或点「原版启动」对比。" % payload)

                elif kind == "deploy_failed":
                    self.installing = False
                    self.status.set("安装失败，详见下方日志。")
                    messagebox.showerror(
                        "安装失败", "详见下方日志。\n游戏目录可能未发生变化。")
        except queue.Empty:
            pass


def main():
    args = [a for a in sys.argv[1:] if a != "--build"]
    do_build = "--build" in sys.argv[1:]

    if missing_outputs(need_pack=not do_build):
        print("[patch] ERROR: build output is incomplete:", file=sys.stderr)
        for name in missing_outputs(need_pack=not do_build):
            print("[patch]   missing:", name, file=sys.stderr)
        return 1

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App(do_build=do_build)
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
