# -*- coding: utf-8 -*-
"""pr2ctl.settings —— 记住游戏目录与上次选择。"""

from .base import *  # noqa: F401,F403

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

