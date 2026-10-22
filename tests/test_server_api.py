# -*- coding: utf-8 -*-
"""服务端 API 冒烟测试：所有 GET 路由都必须 200，不能 500。

这条测试专门防「路由被塞到错误的 dispatch 里」这类回归：之前 POST
处理器混进 get_api，GET 到那些路径会因为引用不存在的 body 直接 500。
"""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "editor", "server.py")

GET_URLS = [
    "/api/health",
    "/api/font-status",
    "/api/langs",
    "/api/count?lang=zh",
    "/api/list?lang=zh",
    "/api/entries?offset=0&limit=1&filter=all&lang=zh",
    "/api/entry-info?lang=zh&id=0xc46f793a",
    "/api/context?lang=zh&id=0xc46f793a",
    "/api/rule-trace?lang=zh&id=0xc46f793a",
    "/api/placeholder-meanings?lang=zh&id=0xc46f793a",
    "/api/seed?lang=zh&id=0xc46f793a",
    "/api/terms?lang=zh",
    "/api/find?id=0xc46f793a",
    "/api/ids?q=0xc46f",
    "/api/server/instances",
    "/api/start/status",
    "/api/start/dirs",
    "/api/start/job",
    "/api/start/running",
    "/api/hash-rules",
    "/api/context-batch?ids=0xc46f793a",
]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestServerApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, SERVER, "--no-open", "--port", str(cls.port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/api/health" % cls.port,
                        timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_get_routes(self):
        for url in GET_URLS:
            with self.subTest(url=url):
                try:
                    with urllib.request.urlopen(
                            "http://127.0.0.1:%d%s" % (self.port, url),
                            timeout=30) as r:
                        self.assertEqual(r.status, 200)
                        json.loads(r.read().decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    self.fail("%s -> HTTP %d" % (url, exc.code))


if __name__ == "__main__":
    unittest.main()
