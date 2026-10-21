# -*- coding: utf-8 -*-
"""Port Royale 2 本地化工具的核心逻辑（无 UI 依赖）。

    base.py      路径常量、已知版本、补丁清单、文件小工具
    detect.py    版本识别、补丁状态、语言包盘点
    deploy.py    复制到游戏目录
    build.py     构建注入器与语言包
    launch.py    启动游戏、拉起编辑器
    settings.py  记住目录与选择

build_install.py（窗口）与 apply_patch.py 都从这里取函数。
"""

from .base import *      # noqa: F401,F403
from .detect import *    # noqa: F401,F403
from .deploy import *    # noqa: F401,F403
from .build import *     # noqa: F401,F403
from .launch import *    # noqa: F401,F403
from .settings import *  # noqa: F401,F403
from .launch import _oserr_hint  # noqa: F401
