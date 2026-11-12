# -*- coding: utf-8 -*-
"""一次 API 请求：已解析的 query / body，加上发响应的两个出口。

路由函数都写成 `f(req)`，可以继续用 `req.send_json(...)`——这样从
server.py 搬过来的分支不用改写返回方式。
"""


class Req:
    __slots__ = ("handler", "query", "body")

    def __init__(self, handler, query=None, body=None):
        self.handler = handler
        self.query = query or {}
        self.body = body or {}

    def q(self, key, default=""):
        values = self.query.get(key)
        return values[0] if values else default

    def send_json(self, obj, status=200):
        return self.handler.send_json(obj, status)

    def send_error_json(self, status, message):
        return self.handler.send_error_json(status, message)
