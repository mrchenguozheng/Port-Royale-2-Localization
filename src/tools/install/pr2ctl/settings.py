# -*- coding: utf-8 -*-
"""pr2ctl.settings —— 记住游戏目录与上次选择。"""

from .base import *  # noqa: F401,F403
from .detect import read_ini_language, write_ini_language

def settings_path():
    """设置文件：优先 %LOCALAPPDATA%，没有就放仓库 build\\ 下。"""
    override = os.environ.get("PR2_SETTINGS")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return os.path.join(base, "PR2Localization", "settings.json")
    return os.path.join(ROOT, "build", "settings.json")


def load_settings():
    path = settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("dirs", {})
            data.setdefault("current", "")
            data.setdefault("last_dir", "")
            return data
    except (OSError, ValueError):
        pass
    return {"dirs": {}, "current": "", "last_dir": ""}


def save_settings(data):
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False



def get_language():
    """上次选择的游戏语言（没有就返回空串）。"""
    return str(load_settings().get("language") or "")


def set_game_language(target, code):
    """唯一的 locale.ini 写入口：游戏目录 + build 模板，并记住选择。

    返回 (是否写入成功, 实际语言)。
    """
    code = (code or "").strip()
    st = load_settings()
    st["language"] = code
    save_settings(st)

    ok = False
    game_ini = os.path.join(target, PACK_DIR, "locale.ini")
    if os.path.isdir(os.path.dirname(game_ini)):
        ok = write_ini_language(game_ini, code)

    build_ini = os.path.join(BUILD, PACK_DIR, "locale.ini")
    if os.path.isdir(os.path.dirname(build_ini)):
        write_ini_language(build_ini, code)
    return ok, code


def game_language(target):
    """游戏目录当前语言：优先 locale.ini，其次设置里记住的。"""
    ini = os.path.join(target, PACK_DIR, "locale.ini")
    return read_ini_language(ini) or get_language()
