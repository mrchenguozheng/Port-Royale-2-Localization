# -*- coding: utf-8 -*-
"""编辑器服务端按域拆出来的模块。

只放不依赖 HTTP handler 的逻辑：数据读写、各域路由处理函数。
`server.py` 负责常量、启动与编解码，这里不 import server，避免循环。
"""
