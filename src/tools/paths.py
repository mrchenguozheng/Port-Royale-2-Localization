# -*- coding: utf-8 -*-
"""tools 的公共路径。脚本按目录分组后，统一从这里取仓库位置。"""

import os

TOOLS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
DATA = os.path.join(TOOLS, "data")
