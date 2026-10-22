# -*- coding: utf-8 -*-
"""pr2ctl.build —— 调 cl.exe 构建注入器，编译语言包。"""

from .base import *  # noqa: F401,F403
from .detect import missing_outputs, read_ini_language

def child_env():
    r"""子进程环境：UTF-8 + 无缓冲。

    Windows 上 Python 给文本流套的是**控制台代码页**（简体中文机器是
    cp936），而这里把管道按 utf-8 解 —— 两边不一致，中文输出就成了
    一串「已生成」模样的乱码。PYTHONIOENCODING 管的就是文本流本身，
    比事后猜编码可靠（猜错了会把正常文本也毁掉）。

    PYTHONUNBUFFERED：输出要实时进日志，不能攒够一块才吐。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def read_lines(proc, events):
    r"""把子进程的输出逐行送进队列。

    Python 子进程由 child_env() 统一成 UTF-8；MSVC 的 cl.exe 不受它
    影响，按控制台代码页写中文提示。所以每行先按 utf-8 解，解不动
    再退回代码页 —— 只在确实解不出时才换，不会把正常文本弄坏。
    """
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError:
            # mbcs = 系统 ANSI 代码页（简体中文机器是 cp936），
            # 也就是 cl.exe 写中文提示时用的那套。不用
            # getpreferredencoding()：开了 UTF-8 模式的 Python 会
            # 把它报成 utf-8，退回原处等于没退。
            line = line.decode("mbcs", "replace")
        events.put(("line", line))


def build_pack(lang, out_dir, events):
    """在子进程里跑 compile_pack.py，把输出送到事件队列。

    不直接 import 它：那个脚本会做 import-time 的路径推导，而且
    它的 stdout 是给命令行看的，逐行读回来反而更可控 —— 失败时
    整个 stderr 都能显示出来。

    脚本自己已经在「编不出条目」时报错退出码 1 且不写文件了。
    这里仍查一次条目数兜底：空包装进游戏等于没生效，而 GUI 是
    会把它复制过去的最后一道关口。
    """
    script = os.path.join(HERE, "pack", "compile_pack.py")
    # --no-fonts：字体由 run_build 在所有语言编完后统一做一次，
    # 免得选三种语言就重裁三遍字体。
    cmd = [sys.executable, script, "--lang", lang, "--out", out_dir, "--no-fonts"]
    events.put(("line", "[%s] 编译中…" % lang))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, env=child_env(),
    )
    read_lines(proc, events)
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
    """语言包里的条目数。空行与 # 注释行不算条目。"""
    if not os.path.isfile(pack_path):
        return 0
    n = 0
    with open(pack_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def build_injector(events):
    """在子进程里跑 build_injector.bat，编译 PR2TextSource.dll 与
    PR2Launcher.exe。

    走 bat 而不是直接调 cl：脚本自己会定位 MSVC 与 SDK，那是它的职责；
    这里只负责把输出转成事件、以及把退出码如实带回来。
    """
    events.put(("line", "[注入器] 编译中…"))
    proc = subprocess.Popen(
        ["cmd", "/c", INJECTOR_BAT, "--no-pause"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, env=child_env(),
    )
    read_lines(proc, events)
    code = proc.wait()

    missing = missing_outputs(need_pack=False)
    if code == 0 and missing:
        code = 1
        events.put(("line", "[注入器] 失败：产物不完整，缺少 %s"
                             % "、".join(missing)))
    elif code == 0:
        events.put(("line", "[注入器] 完成，%s"
                             % "、".join(FLAT_FILES)))
    else:
        events.put(("line", "[注入器] 失败，退出码 %d" % code))
    events.put(("injector_done", code))
    return code


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

        # locale.ini 决定 DLL 读哪个语言包。它是**可写的配置**，不是纯
        # 模板：GUI 改语言时会直接写 build\PR2Packs\locale.ini（以及游戏
        # 目录那份）。所以这里只在它还不存在时才用 src\locale.ini 兜底
        # 建一份 —— 无条件覆盖会把用户刚选的语言打回 language=zh。
        ini_out = os.path.join(PACK_OUT, "locale.ini")
        if os.path.isfile(ini_out):
            events.put(("line", "已保留现有 %s\\locale.ini（%s）"
                        % (PACK_DIR, read_ini_language(ini_out) or "未设置")))
        elif os.path.isfile(LOCALE_INI):
            shutil.copy2(LOCALE_INI, ini_out)
            events.put(("line", "已按 %s 建立 %s\\locale.ini"
                        % (os.path.basename(LOCALE_INI), PACK_DIR)))
        else:
            events.put(("line", "缺少 %s，无法建立 %s\\locale.ini，"
                                "游戏将全程显示英文"
                        % (LOCALE_INI, PACK_DIR)))
            events.put(("build_failed", ""))
            return

        # 字体：语言包编完后统一检查一次。译文里出现新字而字体没跟上，
        # 游戏里就画成空白 —— 所以并进同一个构建动作，别让人单记一步。
        try:
            sys.path.insert(0, os.path.join(HERE, "font"))
            import subset_fonts
            events.put(("line", "检查字体…"))
            ok, msg = subset_fonts.ensure_fonts(
                langs=langs, log=lambda m: events.put(("line", m)))
            events.put(("line", "字体：" + msg))
        except Exception as exc:                  # 字体失败不该让构建失败
            events.put(("line", "字体检查跳过：%s" % exc))

        # 术语对照表：同样是「跟着译文走」的产物，顺手重生成一份，
        # 省得改完译文忘了同步。产物在 build\glossary\，不进仓库。
        try:
            script = os.path.join(HERE, "glossary.py")
            events.put(("line", "生成术语对照…"))
            cmd = [sys.executable, script]
            for l in langs:
                cmd += ["--lang", l]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=ROOT, env=child_env())
            read_lines(proc, events)
            proc.wait()
        except Exception as exc:
            events.put(("line", "术语对照跳过：%s" % exc))

        events.put(("build_ok", list(langs)))
    except Exception as exc:                      # 兜底，别让线程静默死掉
        events.put(("line", "构建出错：%s" % exc))
        events.put(("build_failed", ""))

