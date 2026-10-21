#!/usr/bin/env python3
# coding: utf-8
r"""src/tools/build_install.py — Port Royale 2 本地化工具窗口

界面层：只做显示与回调，真正的逻辑在 pr2ctl（src/tools/pr2ctl/）。
窗口分三段，段号就是步骤号：构建 → 部署 → 启动。

PR2.exe 全程不被修改；部署后用游戏目录里的 PR2Launcher.exe 启动。
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pr2ctl import *  # noqa: F401,F403

# ------------------------------------------------------------ 界面

#: 危险动作统一用这个红。白字 + 深红底，和窗口里其它按钮一眼分开。
_DANGER_BG = "#b3261e"
_DANGER_BG_HOVER = "#8c1d18"


class ConfirmDialog(tk.Toplevel):
    """自定义确认框 —— 按钮文字自己定，不用「是/否」。

    messagebox 只给「是的 / 否」，对「删除补丁」这种事说不清：用户看到的
    「要继续吗？」配「是」并不告诉他按下之后会做什么。这里把动词写在按钮上
    （「继续删除」「确认删除」），并且让危险按钮是红的。

    body 里的清单直接换行显示，所以「第二次确认看不到要删什么」不会再发生。

    choices 给出时，正文下面会列成一排复选框（默认全勾），只有勾选的才算数；
    self.selected 返回勾中的那些。一个都不勾时按「确认」不会关窗，而是提示 ——
    否则按下去等于什么都没做，用户却以为删过了。
    """

    def __init__(self, master, title, body, ok_text, cancel_text="取消",
                 danger=True, choices=None):
        super().__init__(master)
        self.result = False
        self._choices = list(choices or [])
        self.selected = []                        # 默认一个都不勾
        self.vars = []
        self.title(title)
        self.transient(master)
        self.resizable(False, False)

        box = ttk.Frame(self, padding=16)
        box.pack(fill="both", expand=True)

        head = ttk.Frame(box)
        head.pack(fill="x")
        ttk.Label(head, text="⚠", foreground=_DANGER_BG,
                  font=("Segoe UI", 16, "bold")).pack(side="left", padx=(0, 8))
        ttk.Label(head, text=title,
                  font=("Segoe UI", 10, "bold")).pack(side="left")

        ttk.Label(box, text=body, justify="left", wraplength=560).pack(
            fill="x", pady=(10, 10))

        if choices:
            wrap = ttk.Frame(box, borderwidth=1, relief="solid", padding=8)
            wrap.pack(fill="x", pady=(0, 10))
            allvar = tk.BooleanVar(value=False)

            def toggle_all():
                for v in self.vars:
                    v.set(allvar.get())

            ttk.Checkbutton(wrap, text="全选 / 全不选", variable=allvar,
                            command=toggle_all).pack(anchor="w", pady=(0, 4))
            for c in choices:
                v = tk.BooleanVar(value=False)
                self.vars.append(v)
                ttk.Checkbutton(wrap, text=c, variable=v).pack(
                    anchor="w", padx=(18, 0))

        self.warn = ttk.Label(box, text="", foreground=_DANGER_BG)
        self.warn.pack(fill="x")

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        if danger:
            ok = tk.Button(row, text=ok_text, command=self._ok,
                           fg="white", bg=_DANGER_BG,
                           activebackground=_DANGER_BG_HOVER,
                           activeforeground="white", relief="flat",
                           padx=14, pady=3, cursor="hand2")
        else:
            ok = ttk.Button(row, text=ok_text, command=self._ok)
        ok.pack(side="right")
        cancel = ttk.Button(row, text=cancel_text, command=self._cancel)
        cancel.pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self._cancel())
        self.bind("<Return>", lambda e: self._ok())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        try:
            px, py = master.winfo_rootx(), master.winfo_rooty()
            pw, ph = master.winfo_width(), master.winfo_height()
            w, h = self.winfo_width(), self.winfo_height()
            self.geometry("+%d+%d" % (px + (pw - w) // 2, py + (ph - h) // 3))
        except tk.TclError:
            pass
        self.grab_set()
        cancel.focus_set()          # 默认落在「取消」上，回车不会误删

    def _ok(self):
        if self.vars:
            self.selected = [c for c, v in zip(self._choices, self.vars) if v.get()]
            if not self.selected:
                self.warn.configure(
                    text="一个都没勾选 —— 这样不会删除任何东西。取消或至少勾一项。")
                return
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class App(tk.Tk):
    POLL_MS = 80
    #: 构建结束后按钮还要多锁一会儿。构建常常不到一秒，禁用状态
    #: 一闪而过，用户会以为没生效而连点；这段时间里重复构建
    #: 也确实没有意义（产物一样）。
    BUILD_COOLDOWN_MS = 1200

    def __init__(self, do_build):
        super().__init__()
        self.title("Port Royale 2 本地化工具")
        self.resizable(True, True)
        self.minsize(560, 520)

        self.events = queue.Queue()
        self.worker = None
        self.built_langs = []
        self.total = 0
        self.done = 0
        self.building = False
        self.compiling = False
        self.installing = False
        self.editing = False
        #: 编辑器准备工作开始的时刻 + 当前在第几步 —— 用来在状态栏里
        #: 显示「已等 N 秒」，让用户看得出它是在干活，而不是卡住了。
        self._editor_t0 = 0.0
        self._editor_step = ""
        #: 编辑器服务的 pid / 端口 / 句柄。本窗口起的，或者探测到的旧实例。
        #: 收了 pid 才能在关窗口时把它一起停掉，也才知道「停止」按钮该不该亮。
        self.editor_pid = None
        self.editor_proc = None
        self.editor_port = None
        #: 轮询计数：编辑器存活检查不用每 80ms 做一次。
        self._tick = 0
        self.installed_done = True
        self.build_cool = 0
        self.missing_injector = missing_outputs(need_pack=False)

        self.var_dir = tk.StringVar()
        #: 已记住的游戏版本（按 PR2.exe 的 SHA-256 索引）与当前选中项
        self.settings = load_settings()
        self.var_version = tk.StringVar()
        self._version_items = []
        self.status = tk.StringVar()
        #: 启动语言下拉。FOLLOW_LANG 是「不指定」，让 locale.ini 说话。
        self.var_lang = tk.StringVar(value=FOLLOW_LANG)
        #: 缓存游戏目录里已装的语言，换目录时用它判断列表要不要刷新。
        self.installed = []
        #: 下拉显示项（缺包时带「（未构建）」）与代码的映射。
        self.lang_items = []
        self.lang_map = {}

        langs = available_langs()
        self.vars = {}
        for code in langs:
            v = tk.BooleanVar(value=True)
            self.vars[code] = v

        self._build_ui(langs, do_build)
        self._refresh_version_choices()
        self._restore_last_dir()
        self._sync()
        self._center()
        self._poll_id = self.after(self.POLL_MS, self._poll)

    # ---- 布局

    def _build_ui(self, langs, do_build):
        frm = tk.Frame(self, padx=14, pady=10)
        frm.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        # 日志吸收多余高度：窗口拉高时它变高，而不是按钮之间被撑开。
        self.rowconfigure(7, weight=1)

        # 分三段，顺序就是使用顺序：构建 -> 部署 -> 启动。
        # 每段一个 LabelFrame，读起来是步骤而不是控件堆。
        build_box = ttk.LabelFrame(frm, text="1  构建", padding=10)
        build_box.grid(row=0, column=0, sticky="we")
        build_box.columnconfigure(1, weight=1)

        deploy_box = ttk.LabelFrame(frm, text="2  部署到游戏目录", padding=10)
        deploy_box.grid(row=1, column=0, sticky="we", pady=(12, 0))
        deploy_box.columnconfigure(1, weight=1)

        run_box = ttk.LabelFrame(frm, text="3  启动", padding=10)
        run_box.grid(row=2, column=0, sticky="new", pady=(12, 0))

        # 编辑器不在三段流程里 —— 它改的是仓库里的译文，不碰游戏目录。
        # 硬塞进「构建」段会让人以为构建语言包要先开编辑器，所以单列一段。
        edit_box = ttk.LabelFrame(frm, text="4  译文编辑器（可选）", padding=10)
        edit_box.grid(row=3, column=0, sticky="we", pady=(12, 0))

        self._build_section(build_box, langs)
        self._deploy_section(deploy_box)
        self._run_section(run_box)
        self._editor_section(edit_box)
        # 开窗时游戏目录还是空的，先给一个只有「跟随」的下拉；
        # refresh_langs() 会在选定目录或装完之后填上真实语言。
        self.lang_box.configure(values=[FOLLOW_LANG])

        # -- 进度与日志。放在最后：它是结果，不是入口。
        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=1.0)
        self.bar.grid(row=4, column=0, sticky="we", pady=(16, 2))
        self.lbl_status = tk.Label(
            frm, textvariable=self.status, anchor="w", justify="left")
        # 间距挂在状态行自己身上：进度条空闲时是 grid_remove 掉的，
        # 把间距挂在它上面等于空闲时什么间距都没有。
        self.lbl_status.grid(row=5, column=0, sticky="we", pady=(12, 0))

        ttk.Label(frm, text="日志").grid(row=6, column=0, sticky="w",
                                         pady=(10, 2))
        self.log = tk.Text(frm, height=8, width=62, state="disabled",
                           wrap="word", bg="#f4f4f4", relief="solid",
                           borderwidth=1)
        self.log.grid(row=7, column=0, sticky="nsew", pady=(0, 0))

        if self.missing_injector:
            self.status.set("注入器未构建，请先点上方按钮。")
        else:
            self.status.set("就绪")
        self._refresh_injector_label()

        if do_build:
            self.after(120, self.on_build)

    def _build_section(self, box, langs):
        """注入器与语言包。两行，各自独立触发。"""
        ttk.Label(box, text="注入器").grid(row=0, column=0, sticky="w")
        self.btn_injector = ttk.Button(
            box, text="构建注入器（DLL + 启动器）",
            command=self.on_build_injector)
        self.btn_injector.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.lbl_injector = tk.Label(box, anchor="w", justify="left")
        self.lbl_injector.grid(row=0, column=2, sticky="w", padx=(10, 0))

        ttk.Label(box, text="语言包").grid(
            row=1, column=0, sticky="nw", pady=(8, 0))

        # 勾选项按固定列宽铺开，满了自动换行。
        # 单行无限拉伸在语言多时会把窗口撑到比屏幕还宽，右侧的
        # 「构建所选语言」按钮会跑出屏幕点不到。
        cols = max(4, min(6, len(langs) or 1))
        lang_grid = ttk.Frame(box)
        lang_grid.grid(row=1, column=1, columnspan=2, sticky="w",
                       padx=(10, 0), pady=(8, 0))
        if langs:
            for i, code in enumerate(langs):
                ttk.Checkbutton(
                    lang_grid, text=code, variable=self.vars[code],
                    command=self._sync,
                ).grid(row=i // cols, column=i % cols, sticky="w",
                       padx=(0, 14), pady=(0, 2))

            # 按钮无条件创建：_sync 每轮轮询都要访问它，
            # 只在有语言时建会直接 AttributeError。
            rows = (len(langs) + cols - 1) // cols
            self.btn_build = ttk.Button(
                box, text="构建所选语言", command=self.on_build)
            self.btn_build.grid(row=rows + 1, column=0, columnspan=3,
                                sticky="w", pady=(8, 0))
        else:
            tk.Label(lang_grid, text="src\\translations\\ 下没有可构建的语言",
                     fg="#a00000").grid(row=0, column=0, sticky="w")
            self.btn_build = ttk.Button(
                box, text="构建所选语言", command=self.on_build,
                state="disabled")
            self.btn_build.grid(row=1, column=1, sticky="w", pady=(8, 0))

    def _deploy_section(self, box):
        """版本识别 + 游戏目录 + 部署。

        版本一段放在最上面：先认出是哪个构建，再决定用哪个目录，
        顺序与用户的心智一致（「我装的是哪个版本」→「它在哪」）。
        """
        ttk.Label(box, text="已知版本").grid(row=0, column=0, sticky="w")
        self.version_box = ttk.Combobox(
            box, textvariable=self.var_version, state="readonly", width=44)
        self.version_box.grid(row=0, column=1, sticky="we", padx=(10, 0))
        self.version_box.bind("<<ComboboxSelected>>", self.on_pick_version)

        ver_btns = ttk.Frame(box)
        ver_btns.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.btn_remember = ttk.Button(
            ver_btns, text="记住当前目录", width=12, command=self.on_remember_version)
        self.btn_remember.grid(row=0, column=0)
        self.btn_check = ttk.Button(
            ver_btns, text="检查补丁…", width=10, command=self.on_check_patch)
        self.btn_check.grid(row=0, column=1, padx=(6, 0))

        self.lbl_version = tk.Label(box, text="", anchor="w", justify="left")
        self.lbl_version.grid(row=1, column=0, columnspan=3, sticky="w",
                              pady=(4, 0))

        ttk.Label(box, text="游戏目录").grid(row=2, column=0, sticky="w",
                                            pady=(10, 0))
        dir_row = ttk.Frame(box)
        dir_row.grid(row=2, column=1, sticky="we", padx=(10, 0), pady=(10, 0))
        dir_row.columnconfigure(0, weight=1)
        tk.Entry(dir_row, textvariable=self.var_dir, width=44,
                 state="readonly").grid(row=0, column=0, sticky="we")
        ttk.Button(dir_row, text="浏览…", width=8,
                   command=self.on_browse).grid(row=0, column=1, padx=(6, 0))
        self.btn_install = ttk.Button(
            box, text="复制到游戏目录", width=16, command=self.on_install)
        self.btn_install.grid(row=2, column=2, padx=(10, 0), pady=(10, 0))

        ttk.Label(box, text="须含 %s。只复制构建产物，内容相同就跳过。"
                  % GAME_EXE).grid(row=3, column=0, columnspan=3,
                                   sticky="w", pady=(6, 0))

        # 危险操作：把补丁从游戏目录里删干净。放在部署段里，
        # 但**不**跟着 busy() 一起锁 —— 复制失败时恰恰需要它来善后。
        self.btn_remove = tk.Button(
            box, text="移除补丁（危险）…", command=self.on_remove_patch,
            fg="white", bg=_DANGER_BG, activebackground=_DANGER_BG_HOVER,
            activeforeground="white", relief="flat", padx=10, pady=2,
            cursor="hand2")
        self.btn_remove.grid(row=4, column=2, sticky="e", padx=(10, 0), pady=(8, 0))
        ttk.Label(box, text="只删本补丁的文件：启动器、DLL、语言包与它的日志；"
                  "PR2.exe 不会动。").grid(row=4, column=0, columnspan=2,
                                          sticky="w", pady=(8, 0))

    def _run_section(self, box):
        """启动语言 + 启动与保存。

        启动按钮只在语言**确有变化**时顺手保存，没变化就一个字都不写；
        这次跑哪个语言始终由下拉决定，通过 --lang 传给子进程。
        「保存语言设置」是给「不想进游戏、只想改配置」用的入口，
        走同一条保存路径。
        """
        ttk.Label(box, text="启动语言").grid(row=0, column=0, sticky="w")
        self.lang_box = ttk.Combobox(
            box, textvariable=self.var_lang, state="readonly", width=22)
        self.lang_box.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.lang_box.bind("<<ComboboxSelected>>", self.on_pick_lang)
        ttk.Label(box, text="下拉本身不保存").grid(
            row=0, column=2, sticky="w", padx=(8, 0))

        self.btn_play = ttk.Button(box, text="启动游戏（已注入）",
                                   command=self.on_play)
        self.btn_play.grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.btn_save_lang = ttk.Button(box, text="保存语言设置",
                                        command=self.on_save_lang)
        self.btn_save_lang.grid(row=1, column=1, sticky="w", padx=(8, 0),
                                pady=(10, 0))
        self.btn_vanilla = ttk.Button(box, text="运行游戏（原版）",
                                      command=self.on_vanilla)
        self.btn_vanilla.grid(row=1, column=2, sticky="w", padx=(8, 0),
                              pady=(10, 0))
        ttk.Label(box, text="原版不注入任何组件，也不保存语言设置。"
                  ).grid(row=2, column=0, columnspan=3, sticky="w",
                         pady=(6, 0))
        ttk.Button(box, text="关闭", width=10,
                   command=self.destroy).grid(row=3, column=2, sticky="e",
                                              pady=(10, 0))
        box.columnconfigure(2, weight=1)

    def _editor_section(self, box):
        """译文编辑器入口。跟前三段无关，单列一段。

        编辑器由这个窗口**启动并收尾**：已经开着就复用（不再起第二个），
        窗口关掉就一起停，不留孤儿进程。前端（dist\\ 的静态文件）和后端
        （FastAPI）跑在同一个进程里 —— 服务顺便把前端托管了 ——
        所以这里只有这一个进程要管。
        """
        self.btn_editor = ttk.Button(
            box, text="打开译文编辑器", command=self.on_editor)
        self.btn_editor.grid(row=0, column=0, sticky="w")

        self.btn_editor_stop = ttk.Button(
            box, text="停止编辑器", command=self.on_stop_editor, state="disabled")
        self.btn_editor_stop.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Label(box, text="改 src\\translations\\ 下的译文。不需要装任何依赖；"
                  "关掉本窗口会一并停掉编辑器。").grid(
            row=0, column=2, sticky="w", padx=(10, 0))
        box.columnconfigure(2, weight=1)

    def _forget_editor(self):
        self.editor_pid = None
        self.editor_proc = None
        self.editor_port = None

    def _kill_editor(self):
        """停掉编辑器：先请它自己退，不行再强杀。

        1) /api/shutdown：不给权限问题、也不怕 python.exe 是个中转进程 ——
           真正监听的进程自己退出，控制台窗口跟着关。
        2) taskkill /T：服务没响应（比如卡死）时兜底，杀整棵树。
           只杀父进程会留下还在监听的孤儿，端口继续占着。
        """
        pid = self.editor_pid
        port = self.editor_port
        stopped = editor_shutdown(port) if port else False
        if not stopped:
            # pid 可能是 /api/health 报上来的真实服务进程；还没探测完就关窗口时
            # 只有 Popen 的 pid（可能是中转进程），两种都用 /T 杀整棵树。
            target = pid or (self.editor_proc.pid if self.editor_proc else None)
            if target:
                try:
                    subprocess.run(["taskkill", "/PID", str(target), "/T", "/F"],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                except OSError:
                    pass
        proc = self.editor_proc
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()      # 对自家子进程一定有权限，再兜一道
            except OSError:
                pass
        self._forget_editor()

    def on_stop_editor(self):
        """停掉编辑器。pid 可能是本窗口起的，也可能是探测到的旧实例。"""
        if not self.editor_pid:
            port, info = find_editor()
            if info:
                self.editor_pid = int(info.get("pid") or 0) or None
                self.editor_port = port
        if not self.editor_pid:
            self.status.set("没有找到正在运行的编辑器。")
            self._sync()
            return
        pid = self.editor_pid
        port = self.editor_port
        self._kill_editor()
        # 只看**原来那个端口**：别的实例（或用户自己另开的）不该影响判断。
        if port and editor_health(port):
            self.status.set("停止命令已发出，但编辑器仍在运行。")
            self._log("停止后端口 %d 仍有响应，可能卡住了。" % port)
        else:
            self.status.set("编辑器已停止。")
            self._log("已停止编辑器（pid %d）。" % pid)
        self._sync()

    def on_editor(self):
        if self.busy():
            return
        # 已经有一个在跑（可能是上一次 start 留下的）：复用，不再起第二个。
        # 以前每点一次就新起一个，结果 8777/8778/8779 各躺着一个服务。
        port, info = find_editor()
        if info:
            self.editor_pid = int(info.get("pid") or 0) or None
            self.editor_port = port
            webbrowser.open("http://127.0.0.1:%d/" % port)
            self.status.set("编辑器已在运行（端口 %d），已打开浏览器。" % port)
            self._log("复用已在运行的编辑器：端口 %d，pid %s"
                      % (port, self.editor_pid))
            self._sync()
            return

        self._begin_log("译文编辑器")
        # 起服务本身只要一两秒，但「等它真的答话」最多 20 秒。进度条用
        # 不确定模式，同时状态文字一直在报已经等了多少秒 —— 这样"在启动"
        # 和"卡死了"能一眼分开。
        self.bar.configure(mode="indeterminate")
        self.bar.start(80)
        self._editor_t0 = time.time()
        self._editor_step = "启动服务"
        self.status.set("正在启动编辑器…")
        self.editing = True
        self._set_state(self.btn_editor, "disabled")
        self.worker = threading.Thread(target=self._editor_worker, daemon=True)
        self.worker.start()
        self._sync()

    def _editor_worker(self):
        """启动 + 等服务答话。放线程里是因为等 /api/health 最多要 20 秒，
        放主线程会把窗口冻住 —— 用户会以为程序卡死了。
        """
        ok, message = False, "编辑器准备时出现未知错误。"
        pid, port, proc = None, None, None
        try:
            started, msg, child, token = open_editor()
            if not started:
                ok, message = False, "编辑器启动失败：\n\n" + msg
            else:
                # 先记下句柄：等待期间用户可能直接关窗口，那时要靠它收尾。
                self.editor_proc = child
                # 起进程 ≠ 起来了：要等它真的能回答 /api/health，
                # 否则浏览器会在服务还没监听时打开一个打不开的页面。
                port, info = wait_editor(child, token)
                if not info:
                    ok, message = False, (
                        "编辑器进程起来了，但 20 秒内没有响应。\n\n"
                        "看一下它那个控制台窗口里的报错。")
                else:
                    proc = child
                    pid = int(info.get("pid") or 0) or child.pid
                    webbrowser.open("http://127.0.0.1:%d/" % port)
                    message = "编辑器已启动（端口 %d），浏览器已打开。" % port
                    ok = True
        except Exception as exc:      # 线程里抛出去没人接，界面会一直卡在「准备中」
            ok, message = False, "编辑器准备时出错：%s" % exc
        finally:
            self.events.put(("editor_ready", {"ok": ok, "message": message,
                                              "pid": pid, "port": port,
                                              "proc": proc}))
        if not ok:
            self.events.put(("line", message))

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
        return (self.building or self.compiling or self.installing
                or self.editing)

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

    def _refresh_injector_label(self):
        """按 missing_injector 刷新注入器状态标签。"""
        self.missing_injector = missing_outputs(need_pack=False)
        if self.missing_injector:
            self.lbl_injector.configure(
                text="未构建，缺少：%s" % "、".join(self.missing_injector),
                fg="#a00000")
        else:
            self.lbl_injector.configure(
                text="已就绪（%s）" % "、".join(FLAT_FILES), fg="#006000")

    def _set_state(self, widget, state):
        """只在状态真的变了时才 configure。

        ttk 控件的 active（悬停高亮）是瞬态标志，任何一次 configure()
        都会把它清掉。而 _sync() 由 _poll() 每 80ms 调一次，无条件写
        的话等于每 80ms 擦一次悬停态 —— 鼠标停在按钮上时高亮只闪一下。
        「浏览」和「关闭」不闪，正是因为它们不在 _sync() 里。
        """
        if str(widget["state"]) != state:
            widget.configure(state=state)

    def _sync(self):
        locked = self.busy()
        self._set_state(
            self.btn_install,
            "normal" if (not locked
                         and not self.missing_injector
                         and bool(self.built_langs)
                         and is_game_dir(self.var_dir.get()))
            else "disabled")
        self._set_state(
            self.btn_play,
            "normal" if self.ready_to_play() else "disabled")
        # 没有需要保存的东西时禁用「保存语言设置」：按钮本身就是
        # 「这里有变化要落盘」的提示，亮着却什么都不做等于骗人。
        self._set_state(
            self.btn_save_lang,
            "normal" if (not locked and self.lang_to_save()) else "disabled")
        self._set_state(
            self.btn_vanilla,
            "normal" if self.ready_to_vanilla() else "disabled")
        self._set_state(
            self.btn_build,
            "disabled" if locked or self.build_cool or not self.vars
            else "normal")
        self._set_state(
            self.btn_injector,
            "disabled" if locked else "normal")
        self._set_state(
            self.btn_editor,
            "disabled" if locked else "normal")
        # 「停止编辑器」只在确实知道有个实例在跑时才是亮的。
        self._set_state(
            self.btn_editor_stop,
            "normal" if (not locked and self.editor_pid) else "disabled")
        # 没有已装语言包时无法指定语言，下拉只剩「跟随 locale.ini」。
        self._set_state(
            self.lang_box,
            "readonly" if (not locked and self.installed) else "disabled")
        # 空闲时不显示进度条：一条 0% 的灰带看着像卡住了。
        # grid 过的控件用 grid_remove 收起来，不影响它继续占同一格。
        # 同样只在真的需要时调，grid/grid_remove 也是重绘。
        if self.busy():
            if not self.bar.winfo_ismapped():
                self.bar.grid()
        elif self.bar.winfo_ismapped():
            self.bar.grid_remove()

    def _log(self, text):
        """追加一行日志。只追加，不清空 —— 日志是唯一的排查线索。"""
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self._trim_log()
        self.log.see("end")
        self.log.configure(state="disabled")

    def _trim_log(self):
        """超量时丢最老的行，保留最近的 LOG_MAX_LINES 行。"""
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self.log.delete("1.0", "%d.0" % (lines - LOG_MAX_LINES))

    def _begin_log(self, title):
        """开始一个新操作：空一行 + 标题行，好把几段记录分开。"""
        self._log("")
        self._log("── %s ── %s" % (title, time.strftime("%H:%M:%S")))

    # ---- 事件

    def on_build(self):
        if self.busy() or self.build_cool:
            return
        langs = self.selected_langs()
        if not langs:
            messagebox.showwarning("没有选择", "请至少勾选一种语言。")
            return
        self._begin_log("构建语言包：%s" % "、".join(langs))
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

    def on_build_injector(self):
        if self.busy():
            return
        self._begin_log("构建注入器")
        self.bar.configure(value=0.0, maximum=1.0)
        # 先置位再起线程，理由同 on_build。
        self.compiling = True
        self.status.set("正在编译注入器…")
        self.worker = threading.Thread(
            target=build_injector, args=(self.events,), daemon=True)
        self.worker.start()
        self._sync()

    def on_browse(self):
        chosen = filedialog.askdirectory(
            title="选择 Port Royale 2 的游戏目录（需包含 %s）" % GAME_EXE,
            mustexist=True)
        if chosen:
            self.set_dir(chosen)

    def set_dir(self, path):
        path = os.path.normpath(path)
        self.var_dir.set(path)
        self.refresh_langs()
        if not is_game_dir(path):
            self.status.set("该目录里没有 %s，请选游戏所在目录。" % GAME_EXE)
        else:
            self._sync_lang_display()
            self._auto_remember(path)
        self._update_version_status()
        self._sync()

    # ---- 版本记忆

    def _refresh_version_choices(self):
        """把已记住的版本填进下拉框（按上次使用时间倒序）。"""
        dirs = self.settings.get("dirs") or {}
        items = []
        for sha, rec in dirs.items():
            d = rec.get("dir") or ""
            if not d:
                continue
            items.append((rec.get("last_used") or "", sha, d))
        items.sort(reverse=True)
        self._version_items = [(sha, d) for _t, sha, d in items]
        labels = ["%s — %s" % (version_label(sha), d) for sha, d in self._version_items]
        self.version_box.configure(values=labels)
        cur = self.settings.get("current") or ""
        for i, (sha, _d) in enumerate(self._version_items):
            if sha == cur:
                self.var_version.set(labels[i])
                break
        else:
            self.var_version.set("")

    def _restore_last_dir(self):
        """启动时恢复上次的目录；没有就用最近记住的那个。"""
        last = (self.settings.get("last_dir")
                or (self._version_items[0][1] if self._version_items else ""))
        if last and is_game_dir(last):
            self.set_dir(last)

    def _auto_remember(self, path):
        """识别并静默记住当前目录（不弹窗，失败只写日志）。"""
        sha, build = identify_dir(path)
        if not sha:
            return
        dirs = self.settings.setdefault("dirs", {})
        rec = dirs.get(sha, {})
        rec.update({"dir": path, "label": version_label(sha),
                    "last_used": time.strftime("%Y-%m-%d %H:%M:%S")})
        dirs[sha] = rec
        self.settings["current"] = sha
        self.settings["last_dir"] = path
        save_settings(self.settings)
        self._refresh_version_choices()
        if build:
            self._log("识别到 %s（%s）" % (build["label"], sha[:12]))
        else:
            self._log("未识别的 PR2.exe（%s），仍可记住该目录。" % sha[:12])

    def _update_version_status(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            self.lbl_version.configure(
                text="未选择游戏目录，或目录里没有 %s。" % GAME_EXE, fg="#a00000")
            return
        sha, build = identify_dir(path)
        if not sha:
            self.lbl_version.configure(text="无法读取 %s。" % GAME_EXE, fg="#a00000")
            return
        known = "已记住" if sha in (self.settings.get("dirs") or {}) else "未记住"
        if build:
            self.lbl_version.configure(
                text="%s ｜ %s ｜ SHA %s… ｜ %s" % (build["label"], known, sha[:12], build["note"]),
                fg="#006000")
        else:
            self.lbl_version.configure(
                text="未知版本 ｜ %s ｜ SHA %s…（可用「记住当前目录」保存）" % (known, sha[:12]),
                fg="#a06000")

    def on_pick_version(self, _event=None):
        idx = self.version_box.current()
        if 0 <= idx < len(self._version_items):
            sha, path = self._version_items[idx]
            self.settings["current"] = sha
            self.settings["last_dir"] = path
            save_settings(self.settings)
            if is_game_dir(path):
                self.set_dir(path)
            else:
                self.status.set("该版本的目录已不存在：%s" % path)

    def on_remember_version(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            messagebox.showinfo("记住当前目录", "请先选择一个包含 %s 的游戏目录。" % GAME_EXE)
            return
        sha, build = identify_dir(path)
        if not sha:
            messagebox.showerror("记住当前目录", "读取 %s 失败。" % GAME_EXE)
            return
        self._auto_remember(path)
        self._update_version_status()
        label = build["label"] if build else "未知版本"
        messagebox.showinfo("记住当前目录",
                            "已记住：\n%s\n%s\n\nSHA-256：%s" % (label, path, sha))

    def on_check_patch(self):
        path = self.var_dir.get()
        if not is_game_dir(path):
            messagebox.showinfo("检查补丁", "请先选择一个包含 %s 的游戏目录。" % GAME_EXE)
            return
        rows = patch_report(path)
        lines = ["%s：%s%s" % (name, state, ("  — " + note) if note else "")
                 for name, state, note in rows]
        sha, build = identify_dir(path)
        head = build["label"] if build else "未知版本"
        messagebox.showinfo(
            "补丁状态 — %s" % head,
            "\n".join(lines) + "\n\nSHA-256：%s" % sha)

    def _sync_lang_display(self):
        """把 locale.ini 的设置显示到下拉框上，并说明读到了什么。

        三种情况分别给出不同的说法，免得用户对着一个说不清的下拉框
        猜游戏到底会跑哪种语言：
          · 文件在且有language=  -> 下拉显示那个语言，状态说明来源
          · 文件在但没有language= -> 下拉退回「跟随」，状态说明会看英文
          · 文件不存在（还没复制过去）-> 下拉退回「跟随」，状态说明复制完才有
        """
        d = self.var_dir.get()
        pack = os.path.join(d, PACK_DIR)
        ini = os.path.join(pack, "locale.ini")

        if not os.path.isdir(pack):
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("找到 %s，但还没有 %s\\ —— 先构建并复制过去。"
                            % (GAME_EXE, PACK_DIR))
            return

        if not os.path.isfile(ini):
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("找到 %s，但没有 %s\\locale.ini —— "
                            "语言未设置，游戏会显示英文。"
                            % (GAME_EXE, PACK_DIR))
            return

        code = read_ini_language(ini)
        if not code:
            self.var_lang.set(FOLLOW_LANG)
            self.status.set("%s\\locale.ini 里没有 language=，"
                            "游戏会显示英文。" % PACK_DIR)
            return

        self.var_lang.set(code if code in self.installed else FOLLOW_LANG)
        if code in self.installed:
            self.status.set("当前语言：%s（读自 %s\\locale.ini）。"
                            % (code, PACK_DIR))
        else:
            self.status.set("%s\\locale.ini 指定 %s，但游戏目录里没有 "
                            "%s.txt —— 游戏会显示英文。"
                            % (PACK_DIR, code, code))

    def refresh_langs(self):
        """列出 src\\translations 里的全部语言；游戏目录里没有包的标「（未构建）」。

        列表变过才重设 values：Combobox.configure 同样是重绘，
        在 80ms 的轮询路径上无条件写会连带影响交互。
        """
        codes = available_langs()
        installed = installed_langs(self.var_dir.get())
        items = [c if c in installed else c + "（未构建）" for c in codes]
        if items == self.lang_items:
            return
        self.lang_items = items
        self.installed = installed
        self.lang_map = {it: c for it, c in zip(items, codes)}
        self.lang_box.configure(values=[FOLLOW_LANG] + items)
        # 换目录等于换了一份 locale.ini，当前选择可能在新列表里不存在，
        # 这时按新目录的设置重新对齐，而不是留一个选不中的值。
        cur = self.var_lang.get()
        valid = {FOLLOW_LANG} | set(items)
        if cur not in valid:
            ini = self.ini_lang()
            cur = self.display_for(ini) if ini else FOLLOW_LANG
            if cur not in valid:
                cur = FOLLOW_LANG
        self.var_lang.set(cur)

    def display_for(self, code):
        """语言代码 -> 下拉显示项；找不到返回「跟随」。"""
        for item, c in self.lang_map.items():
            if c == code:
                return item
        return FOLLOW_LANG

    def ini_lang(self):
        """游戏目录 locale.ini 里设的语言；读不到返回 None。"""
        d = self.var_dir.get()
        if not d or not os.path.isdir(os.path.join(d, PACK_DIR)):
            return None
        return read_ini_language(os.path.join(d, PACK_DIR, "locale.ini"))

    def chosen_lang(self):
        """下拉当前选中的语言代码；选「跟随 locale.ini」时返回 None。"""
        v = self.var_lang.get()
        if v == FOLLOW_LANG:
            return None
        return self.lang_map.get(v, v)

    def lang_to_save(self):
        """真正需要落盘的语言代码；没有需要保存的返回 None。

        「不写」的理由只有两个，都得是真无变化：
          · 选的是「跟随」—— 本来就没有要保存的东西
          · 游戏目录里已经是这个语言 —— 写回去是逐字节相同的事，
            白白改文件时间戳，也让「我到底动过它没有」变得不可查
        """
        code = self.chosen_lang()
        if code is None:
            return None
        d = self.var_dir.get()
        if d and os.path.isdir(os.path.join(d, PACK_DIR)):
            if read_ini_language(os.path.join(d, PACK_DIR, "locale.ini")) == code:
                return None
        return code

    def on_pick_lang(self, _event=None):
        """下拉改动只记录选择，不落盘。

        启动按钮也用它（不落盘），落盘只有「保存语言设置」一个入口。
        改下拉不发文件：选错了、或者只是想看看别的语言，
        都不该在游戏目录里留下痕迹。
        """
        if self.lang_to_save() is None:
            self.status.set("语言未变（%s）—— 没有需要保存的东西。"
                            % self.var_lang.get())
            return
        self.status.set("已选 %s.txt —— 还没保存，点「启动游戏（已注入）」"
                        "或「保存语言设置」才写入。" % self.chosen_lang())

    def save_lang_choice(self):
        """把下拉里的选择写进 locale.ini。返回 (是否成功, 说明)。

        落盘的唯一实现，调用方是「启动游戏（已注入）」与「保存语言设置」。
        两者走同一条路径，所以不会出现两套保存行为。

        写两处：build\\PR2Packs\\ 与游戏目录那份。前者保证下次构建不会
        把选择打回模板默认值（run_build 只在文件不存在时才用模板），
        后者让下一次启动直接生效，不必先构建一次。

        **无变化时一个字都不写** —— 选了「跟随」或游戏目录已是该语言
        时直接返回，由调用方照样启动（本次语言照样生效，走 --lang）。

        写不成不算失败 —— 本次启动仍会用所选语言（走环境变量），
        只是下次启动会回退，所以只提示不弹窗打断。
        """
        code = self.lang_to_save()
        if code is None:
            return True, "语言没有变化，未写入任何文件。"
        if code not in self.installed:
            return False, ("选了 %s，但游戏目录里还没有 %s.txt —— "
                           "先勾选它构建，再点「部署到游戏目录」。"
                           % (code, code))

        targets = [os.path.join(PACK_OUT, "locale.ini")]
        d = self.var_dir.get()
        if d and os.path.isdir(os.path.join(d, PACK_DIR)):
            targets.append(os.path.join(d, PACK_DIR, "locale.ini"))

        failed = [p for p in targets if not write_ini_language(p, code)]
        if failed:
            return False, ("已选了 %s，但 %s 写不进去（多半是只读）—— "
                           "本次启动仍用 %s，下次启动会回到原来的语言。"
                           % (code,
                              "、".join(os.path.basename(
                                  os.path.dirname(p)) + "\\locale.ini"
                                  for p in failed),
                              code))
        return True, "语言已保存为 %s.txt。" % code

    def on_play(self):
        """启动已注入版。语言确有变化时顺手保存，没变化就一个字都不写。

        保存不是这个按钮独有的功能，而是「有变化就落盘」这条规则的
        唯一实现（save_lang_choice）：无变化时它直接返回，文件不动。
        单独的「保存语言设置」是给「不想进游戏、只想改配置」用的入口，
        走的是同一条路径，不会出现两套保存逻辑。
        """
        lang = self.chosen_lang()
        if lang and lang not in self.installed:
            messagebox.showerror(
                "语言包未构建",
                "选了 %s，但游戏目录里还没有 %s.txt。\n\n"
                "先在上面的「构建」里勾选 %s 构建，再点「部署到游戏目录」。"
                % (lang, lang, lang))
            return
        saved, note = self.save_lang_choice()
        ok, message = launch_game(self.var_dir.get(), lang)
        if not ok:
            messagebox.showerror("无法启动", message)
            return
        self.status.set("%s %s" % (note, message))
        if not saved:
            messagebox.showwarning("语言设置没有保存", note)

    def on_save_lang(self):
        """只保存语言，不启动。"""
        saved, note = self.save_lang_choice()
        self.status.set(note)
        if not saved:
            messagebox.showwarning("语言设置没有保存", note)

    def on_install(self):
        if self.busy():
            return
        langs = list(self.built_langs)
        self._begin_log("复制到游戏目录：%s" % self.var_dir.get())
        self.bar.configure(value=0.0)
        self.status.set("正在复制到 %s …" % self.var_dir.get())
        self.installing = True
        self.worker = threading.Thread(
            target=run_deploy,
            args=(self.var_dir.get(), langs, self.events), daemon=True)
        self.worker.start()
        self._sync()

    def on_remove_patch(self):
        """把补丁从游戏目录删掉 —— 整个窗口里唯一会删东西的地方。

        所以做得比别的操作都啰嗦：
          · 先列出**实际存在**的文件，不是「可能有哪些」；
          · 两次确认**都带清单**，第二次不是「确定吗」这种空话；
          · 按钮写动词（继续删除 / 确认删除），不用含糊的是/否；
          · 每个文件的结果都写进日志，失败（比如游戏正在运行）原样报出来。
        """
        if self.busy():
            return
        d = self.var_dir.get()
        if not is_game_dir(d):
            messagebox.showerror("没有游戏目录",
                                 "先选择一个含 %s 的目录。" % GAME_EXE)
            return

        items = patch_items(d)
        if not items:
            messagebox.showinfo("没有可删的", "这个目录里没有本补丁的文件。")
            return

        names = "\n".join("   " + rel for rel, _p, _isdir in items)

        # 第一次：说清删什么、不删什么、后果。
        dlg = ConfirmDialog(
            self, "从游戏目录移除补丁",
            "目录：\n%s\n\n将删除以下 %d 项：\n%s\n\n"
            "不会删除 PR2.exe、存档、其它 DLL 或其它语言包。\n"
            "删除后游戏回到原版（英文），而且不可撤销。"
            % (d, len(items), names),
            ok_text="继续删除")
        self.wait_window(dlg)
        if not dlg.result:
            return

        # 第二次：逐项复选 —— 只删勾中的。清单再摊一遍，不靠记忆。
        dlg2 = ConfirmDialog(
            self, "再次确认：勾选要删除的文件",
            "下面这些是本补丁在游戏目录里的文件。**只有勾选的会被删除**，"
            "取消勾选的会原样留在目录里。\n\n"
            "删除后无法恢复；PR2.exe、存档、其它 DLL 都不受影响。",
            ok_text="删除勾选项",
            choices=[rel for rel, _p, _isdir in items])
        self.wait_window(dlg2)
        if not dlg2.result:
            return
        chosen = dlg2.selected

        ok, removed, failed = remove_patch(d, only=chosen)

        self._begin_log("移除补丁（勾选 %d / %d 项）：%s"
                        % (len(chosen), len(items), d))
        for r in removed:
            self._log("  已删除 %s" % r)
        for f in failed:
            self._log("  失败 %s" % f)
        for rel, _p, _isdir in items:
            if rel not in chosen:
                self._log("  保留 %s（未勾选）" % rel)

        # 语言包没了，启动语言下拉必须跟着变（否则还列着已经不存在的包）
        self.refresh_langs()
        self.installed_done = False
        self.built_langs = []
        if ok:
            self.status.set("已按勾选删除 %d 项（勾了 %d 项），未勾选的保留。"
                            % (len(removed), len(chosen)))
        else:
            self.status.set("有 %d 项没删掉 —— 游戏可能正在运行。" % len(failed))
            messagebox.showwarning(
                "部分文件没删掉",
                "常见原因是游戏正在运行（文件被占用）。\n关闭游戏后可以再试一次。\n\n"
                "详见下方日志。")
        self._sync()

    def on_vanilla(self):
        ok, message = launch_vanilla(self.var_dir.get())
        if ok:
            self.status.set(message)
        else:
            messagebox.showerror("无法启动", message)

    def on_close(self):
        """关窗口 = 收工：编辑器是 start 拉起来的，也由 start 停掉。

        构建/复制线程都是 daemon，随进程一起结束；编辑器是**独立进程**，
        不主动停就会一直留在后台 —— 以前正是这样，点几次攒几个。
        """
        # 先取消下一轮轮询：窗口都销毁了还回调，Tk 会往 stderr 抛
        # 「invalid command name ...」。
        if getattr(self, "_poll_id", None):
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        if self.editor_pid or self.editor_proc is not None:
            self._kill_editor()
        self.destroy()

    # ---- 队列泵

    def _poll(self):
        self._drain()
        self._tick += 1
        # 编辑器没了（控制台被关掉 / 崩了）就把「停止」按钮和 pid 一起清掉，
        # 免得界面还显示「在运行」。每 40 个轮询（约 3 秒）探一次。
        if self.editor_pid and self._tick % 40 == 0:
            port, info = find_editor()
            if not info:
                self._forget_editor()
                self.status.set("编辑器已退出（控制台窗口被关掉了？）。")
        # 编辑器准备期间每秒刷新一次「已等 N 秒」：进度条在动、数字在走，
        # 才能把「正在下东西」和「已经卡死」区分开。
        if self.editing and self._editor_t0:
            secs = int(time.time() - self._editor_t0)
            if secs >= 1 and secs != getattr(self, "_editor_secs", -1):
                self._editor_secs = secs
                self.status.set("编辑器：%s… 已等 %d 秒"
                                % (self._editor_step or "检查依赖", secs))
        self._sync()
        self._poll_id = self.after(self.POLL_MS, self._poll)

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

                elif kind == "injector_done":
                    self.compiling = False
                    self._refresh_injector_label()
                    if self.missing_injector:
                        self.status.set("注入器编译失败，详见下方日志。")
                    else:
                        self.status.set("注入器已就绪，可以构建语言包了。")

                elif kind == "build_ok":
                    self.end_build()
                    self.built_langs = payload
                    left = missing_outputs()
                    if left:
                        self.status.set("构建结束，但缺少：%s" % "、".join(left))
                    elif is_game_dir(self.var_dir.get()):
                        self.status.set("构建完成，可以复制到游戏目录。")
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
                    self.status.set("正在复制（%d/%d）：%s" % (i, n, label))

                elif kind == "deploy_ok":
                    self.installing = False
                    self.installed_done = True
                    self.bar.configure(value=float(self.bar["maximum"]))
                    # 刚复制进去的语言包现在可以选了。
                    self.refresh_langs()
                    self.status.set("复制完成，可以点「启动游戏（已注入）」。")
                    self._sync()
                    messagebox.showinfo(
                        "复制完成",
                        "已复制到：\n%s\n\n现在可以点「启动游戏（已注入）」，"
                        "或点「运行游戏（原版）」对比。" % payload)

                elif kind == "editor_step":
                    i, n, label = payload
                    self._editor_step = "%s（第 %d/%d 步）" % (label, i, n)
                    self.status.set("编辑器：" + self._editor_step + "…")

                elif kind == "editor_line":
                    self._log("  " + str(payload))

                elif kind == "editor_ready":
                    self.editing = False
                    info = payload
                    ok, message = info["ok"], info["message"]
                    self.editor_pid = info.get("pid")
                    self.editor_port = info.get("port")
                    self.editor_proc = info.get("proc")
                    # 退出不确定模式，交还给构建/复制用的确定模式进度条。
                    self.bar.stop()
                    self.bar.configure(mode="determinate", maximum=1.0, value=0.0)
                    # 失败说明可能有好几行，状态栏只放第一行，全文进日志
                    self.status.set(message.splitlines()[0] if message else "")
                    self._sync()
                    if not ok:
                        self._log(message)
                        messagebox.showerror("编辑器准备失败", message)

                elif kind == "deploy_failed":
                    self.installing = False
                    self.status.set("复制失败，详见下方日志。")
                    messagebox.showerror(
                        "复制失败", "详见下方日志。\n游戏目录可能未发生变化。")
        except queue.Empty:
            pass


def main():
    # 产物缺失不再拦在窗口外面：注入器可以在窗口里现编，
    # 缺什么窗口自己会说。拦在这里等于不给用户补的机会。
    do_build = "--build" in sys.argv[1:]

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
