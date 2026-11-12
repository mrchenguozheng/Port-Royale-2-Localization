# -*- coding: utf-8 -*-
""""安装"域：游戏目录、构建/部署/启动任务、字体状态与导出。

任务用后台线程跑，状态放在 START_JOB；这一块没有 HTTP 代码。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(SRC, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import subprocess
import threading
import time
import sys

from install import pr2ctl as P  # noqa: E402

START_JOB = {"running": False, "lines": [], "done": False, "ok": False,
             "kind": "", "error": ""}
START_LOCK = threading.Lock()


def set_presets_dir(path):
    _font_module().PRESETS_DIR = os.path.abspath(path)


def known_dirs():
    """settings 里记住过的游戏目录，按最近使用排序。"""
    st = P.load_settings()
    cur = st.get("current") or ""
    out = []
    for sha, entry in (st.get("dirs") or {}).items():
        d = entry.get("dir") or ""
        valid = bool(d) and P.is_game_dir(d)
        label = entry.get("label") or (P.version_label(sha) if valid else "")
        out.append({
            "sha": sha,
            "dir": d,
            "label": label,
            "last_used": entry.get("last_used") or "",
            "current": sha == cur,
            "valid": valid,
        })
    out.sort(key=lambda x: x.get("last_used") or "", reverse=True)
    return out


def start_dir():
    """当前游戏目录。current 存的是 PR2.exe 的 SHA，不是路径。"""
    st = P.load_settings()
    cur = st.get("current") or ""
    entry = (st.get("dirs") or {}).get(cur)
    if entry and entry.get("dir"):
        return entry["dir"]
    return cur if os.path.isdir(cur) else (st.get("last_dir") or "")


def start_status():
    d = start_dir()
    info = {"dir": d, "valid": False, "langs": P.available_langs()}
    if d and P.is_game_dir(d):
        sha, build = P.identify_dir(d)
        info.update({
            "valid": True,
            "version": P.version_label(sha),
            "sha": sha,
            "patches": [{"name": n, "exists": True} for n, _p, _d in P.patch_items(d)],
            "packs": P.installed_langs(d),
            "locale": P.read_ini_language(os.path.join(d, P.PACK_DIR, "locale.ini")),
        })
    return info


class _StartEvents:
    """把 core 的事件流写进 START_JOB。"""

    def put(self, ev):
        kind, payload = ev if isinstance(ev, tuple) else ("line", str(ev))
        with START_LOCK:
            if kind == "line":
                START_JOB["lines"].append(payload)
                if len(START_JOB["lines"]) > 500:
                    del START_JOB["lines"][:-500]
            elif kind.endswith("_ok"):
                START_JOB["ok"] = True
            elif kind.endswith("_failed"):
                START_JOB["ok"] = False


def start_run(kind, fn):
    with START_LOCK:
        if START_JOB["running"]:
            return {"ok": False, "error": "已有任务在运行"}
        START_JOB.update(running=True, lines=[], done=False, ok=False,
                         kind=kind, error="")
    ev = _StartEvents()

    def worker():
        try:
            fn(ev)
        except Exception as exc:
            with START_LOCK:
                START_JOB["error"] = str(exc)
                START_JOB["ok"] = False
        finally:
            with START_LOCK:
                START_JOB["running"] = False
                START_JOB["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "kind": kind}


def _font_module():
    """按需把 src/tools/font 加进 sys.path，返回 subset_fonts 模块。"""
    fdir = os.path.join(TOOLS, "font")
    if fdir not in sys.path:
        sys.path.insert(0, fdir)
    import subset_fonts
    return subset_fonts


def font_status():
    """安装页「第一次用」卡片的字体状态（按语言）。"""
    sf = _font_module()
    langs = sf.list_presets()
    base_missing = [n for n in sf.FONTS
                    if not os.path.isfile(os.path.join(sf.DEFAULT_SRC, n))]
    rows = []
    problems = []
    for lang in langs:
        donors, _fallback = sf.load_preset(lang)
        donor_rows = [{"path": sf._resolve(d), "exists": os.path.isfile(sf._resolve(d))}
                      for d, _idx in donors]
        built = sum(1 for n in sf.FONTS
                    if os.path.isfile(os.path.join(sf.DEFAULT_OUT, lang, n)))
        rows.append({"lang": lang, "donors": donor_rows,
                     "built": built, "total": len(sf.FONTS)})
        miss = [d for d in donor_rows if not d["exists"]]
        if miss:
            problems.append("%s 缺 %d 个 donor" % (lang, len(miss)))
    if base_missing:
        problems.append("缺 %d 个原版字体（需要从游戏导出）" % len(base_missing))
    if not sf._fonttools():
        problems.append("缺 fontTools")
    if not langs:
        problems.append("没有 presets/<语言>.toml（可从 presets.example.toml 复制）")
    return {
        "ok": not problems,
        "fonttools": bool(sf._fonttools()),
        "base": {"dir": sf.DEFAULT_SRC, "missing": base_missing,
                 "total": len(sf.FONTS)},
        "languages": rows,
        "problems": problems,
        "presets_dir": sf.PRESETS_DIR,
    }


def get_start_running(req):
    query = req.query
    body = req.body
    procs = P.game_processes()
    return req.send_json({"running": bool(procs), "procs": procs})


def get_font_status(req):
    query = req.query
    body = req.body
    return req.send_json(font_status())


def get_start_status(req):
    query = req.query
    body = req.body
    return req.send_json(start_status())


def get_start_dirs(req):
    query = req.query
    body = req.body
    return req.send_json({"dirs": known_dirs()})


def get_start_job(req):
    query = req.query
    body = req.body
    with START_LOCK:
        return req.send_json(dict(START_JOB))


def post_font_export(req):
    query = req.query
    body = req.body
    game = (body.get("dir") or "").strip()
    if not game:
        return req.send_json({"ok": False, "error": "先填写游戏目录"})
    out = os.path.join(os.path.dirname(SRC), "assets", "fonts", "original")
    script = os.path.join(TOOLS, "font", "extract_fonts.py")
    proc = subprocess.run(
        [sys.executable, script, "--game-dir", game, "--out", out],
        cwd=os.path.dirname(SRC), capture_output=True,
        text=True, encoding="utf-8", errors="replace")
    output = (proc.stdout or "") + (proc.stderr or "")
    return req.send_json({"ok": proc.returncode == 0,
                           "output": output,
                           "status": font_status()})


def post_font_stitch(req):
    query = req.query
    body = req.body
    sf = _font_module()
    lines = []
    langs = body.get("langs") or None
    ok, msg = sf.ensure_fonts(langs=langs,
                              force=bool(body.get("force", True)),
                              log=lines.append)
    return req.send_json({"ok": ok, "message": msg, "log": lines,
                           "status": font_status()})


def post_start_pick(req):
    query = req.query
    body = req.body
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command",
             "Add-Type -AssemblyName System.Windows.Forms; "
             "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
             "$d.Description = '选择 Port Royale 2 游戏目录'; "
             "$d.ShowNewFolderButton = $false; "
             "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
             "{ Write-Output $d.SelectedPath }"],
            capture_output=True, text=True, timeout=180,
            creationflags=0x08000000)
        chosen = (out.stdout or "").strip().splitlines()
        chosen = chosen[-1].strip() if chosen else ""
    except Exception as exc:
        return req.send_json({"ok": False, "error": "打开目录选择框失败：%s" % exc})
    if not chosen:
        return req.send_json({"ok": False, "error": "已取消"})
    return req.send_json({"ok": True, "path": chosen})


def post_start_use(req):
    query = req.query
    body = req.body
    sha = (body.get("sha") or "").strip()
    st = P.load_settings()
    entry = (st.get("dirs") or {}).get(sha)
    if not entry:
        return req.send_json({"ok": False, "error": "没有这个目录"})
    st["current"] = sha
    st["last_dir"] = entry.get("dir") or st.get("last_dir", "")
    P.save_settings(st)
    return req.send_json({"ok": True, **start_status()})


def post_start_forget(req):
    query = req.query
    body = req.body
    sha = (body.get("sha") or "").strip()
    st = P.load_settings()
    dirs = st.get("dirs") or {}
    entry = dirs.pop(sha, None)
    if not entry:
        return req.send_json({"ok": False, "error": "没有这个目录"})
    if st.get("current") == sha:
        st["current"] = ""
        st["last_dir"] = ""
    P.save_settings(st)
    return req.send_json({"ok": True, "dirs": known_dirs()})


def post_start_dir(req):
    query = req.query
    body = req.body
    d = (body.get("path") or "").strip()
    if not P.is_game_dir(d):
        return req.send_json({"ok": False,
                               "error": "该目录里没有 %s" % P.GAME_EXE})
    st = P.load_settings()
    sha, _build = P.identify_dir(d)
    st.setdefault("dirs", {})[sha] = {
        "dir": d,
        "label": P.version_label(sha),
        "last_used": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    st["current"] = sha
    st["last_dir"] = d
    P.save_settings(st)
    return req.send_json({"ok": True, **start_status()})


def post_start_build_injector(req):
    query = req.query
    body = req.body
    return req.send_json(start_run("injector", lambda ev: P.build_injector(ev)))


def post_start_build(req):
    query = req.query
    body = req.body
    langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
    if not langs:
        return req.send_json({"ok": False, "error": "没有勾选语言"})
    return req.send_json(start_run("build", lambda ev: P.run_build(langs, ev)))


def post_start_deploy(req):
    query = req.query
    body = req.body
    langs = [x for x in (body.get("langs") or []) if x in P.available_langs()]
    d = start_dir()
    if not d or not P.is_game_dir(d):
        return req.send_json({"ok": False, "error": "还没有选择游戏目录"})
    return req.send_json(start_run(
        "deploy", lambda ev: P.run_deploy(d, langs or None, ev)))


def post_start_lang(req):
    query = req.query
    body = req.body
    d = start_dir()
    if not d or not P.is_game_dir(d):
        return req.send_json({"ok": False, "error": "还没有选择游戏目录"})
    code = (body.get("lang") or "").strip()
    if code not in P.available_langs():
        return req.send_json({"ok": False, "error": "没有这个语言包：%s" % code})
    ok, code = P.set_game_language(d, code)
    return req.send_json({"ok": ok, "lang": code, **start_status()})


def post_start_kill(req):
    query = req.query
    body = req.body
    ok, msg = P.kill_game()
    return req.send_json({"ok": ok, "message": msg,
                           "procs": P.game_processes()})


def post_start_launch(req):
    query = req.query
    body = req.body
    d = start_dir()
    if not d or not P.is_game_dir(d):
        return req.send_json({"ok": False, "error": "还没有选择游戏目录"})
    lang = body.get("lang") or P.game_language(d) or None
    if body.get("vanilla"):
        ok, msg = P.launch_vanilla(d)
    else:
        ok, msg = P.launch_game(d, lang)
    return req.send_json({"ok": ok, "message": msg})



ROUTES = {
    ("GET", "/api/start/running"): get_start_running,
    ("GET", "/api/font-status"): get_font_status,
    ("GET", "/api/start/status"): get_start_status,
    ("GET", "/api/start/dirs"): get_start_dirs,
    ("GET", "/api/start/job"): get_start_job,
    ("POST", "/api/font/export"): post_font_export,
    ("POST", "/api/font/stitch"): post_font_stitch,
    ("POST", "/api/start/pick"): post_start_pick,
    ("POST", "/api/start/use"): post_start_use,
    ("POST", "/api/start/forget"): post_start_forget,
    ("POST", "/api/start/dir"): post_start_dir,
    ("POST", "/api/start/build-injector"): post_start_build_injector,
    ("POST", "/api/start/build"): post_start_build,
    ("POST", "/api/start/deploy"): post_start_deploy,
    ("POST", "/api/start/lang"): post_start_lang,
    ("POST", "/api/start/kill"): post_start_kill,
    ("POST", "/api/start/launch"): post_start_launch,
}
