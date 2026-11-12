# -*- coding: utf-8 -*-
"""服务端 API 冒烟测试：GET 全 200；POST 写路径只碰临时数据目录。

两条规矩：
1. GET 路由不能 500 —— 防「路由被塞到错误的 dispatch」这类回归；
2. POST 必须用 --data 指向临时副本 —— 以前一跑测试就写真实
   src\\translations\\*.toml，写路径等于没有测试。
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "editor", "server.py")
SRC = os.path.join(ROOT, "src")

GET_URLS = [
    "/api/health",
    "/api/font-status",
    "/api/langs",
    "/api/count?lang=zh",
    "/api/list?lang=zh",
    "/api/entries?offset=0&limit=1&filter=all&lang=zh",
    "/api/entry-info?lang=zh&id=0xc46f793a",
    "/api/rule-trace?lang=zh&id=0xc46f793a",
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


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _repo_files():
    """会被 POST 写到、必须保持不变的仓库文件清单。"""
    out = []
    for sub in (("translations",), ("orig",)):
        d = os.path.join(SRC, *sub)
        if os.path.isdir(d):
            out += [os.path.join(d, n) for n in os.listdir(d)
                    if n.endswith(".toml")]
    for name in ("placeholder_meanings.toml", "hash_rules.toml"):
        p = os.path.join(ROOT, "glossary", name)
        if os.path.isfile(p):
            out.append(p)
    return out


class TestServerApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.data = os.path.join(cls.tmp, "src")
        cls.presets = os.path.join(cls.tmp, "presets")
        for sub in ("translations", "orig"):
            src = os.path.join(SRC, sub)
            dst = os.path.join(cls.data, sub)
            os.makedirs(dst)
            for name in os.listdir(src):
                if name.endswith(".toml"):
                    shutil.copy2(os.path.join(src, name), dst)
        gloss = os.path.join(ROOT, "glossary")
        dst_g = os.path.join(cls.tmp, "glossary")
        os.makedirs(dst_g)
        for name in ("placeholder_meanings.toml", "hash_rules.toml"):
            p = os.path.join(gloss, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dst_g, name))
        os.makedirs(cls.presets)
        repo_presets = os.path.join(SRC, "data", "fontstitch", "presets")
        if os.path.isdir(repo_presets):
            for name in os.listdir(repo_presets):
                if name.endswith(".toml"):
                    shutil.copy2(os.path.join(repo_presets, name),
                                 os.path.join(cls.presets, name))

        cls.repo_digests = {p: _digest(p) for p in _repo_files()}

        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, SERVER, "--no-open", "--port", str(cls.port),
             "--data", cls.data, "--presets-dir", cls.presets],
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
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, url):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d%s" % (self.port, url), timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _post(self, path, body):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _zh_path(self):
        return os.path.join(self.data, "translations", "zh.toml")

    def _zh(self):
        with open(self._zh_path(), "rb") as fh:
            return tomllib.load(fh)

    def test_get_routes(self):
        for url in GET_URLS:
            with self.subTest(url=url):
                try:
                    status, payload = self._get(url)
                    self.assertEqual(status, 200)
                    self.assertIsInstance(payload, (dict, list))
                except urllib.error.HTTPError as exc:
                    self.fail("%s -> HTTP %d" % (url, exc.code))

    def test_newlang_copies_template(self):
        status, body = self._post("/api/newlang",
                                  {"code": "zzr1test", "from": "zh"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("ok"))
        dst = os.path.join(self.data, "translations", "zzr1test.toml")
        self.assertTrue(os.path.isfile(dst))
        with open(dst, "rb") as fh:
            self.assertEqual(len(tomllib.load(fh)), len(self._zh()))
        preset = os.path.join(self.presets, "zzr1test.toml")
        if body.get("presets") is not None:
            self.assertTrue(os.path.isfile(preset), body)
        self.assertIn("zzr1test", self._get("/api/langs")[1]["editable"])

    def test_patch_writes_only_given_id(self):
        before = self._zh()
        hid = next(iter(before))
        new_text = before[hid] + "补"
        status, body = self._post("/api/patch", {
            "lang": "zh", "rows": [{"id": hid, "text": new_text}]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["changed"], 1)
        self.assertEqual(body["written"], len(before))
        after = self._zh()
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[hid], new_text)
        diff = [k for k in before if after[k] != before[k]]
        self.assertEqual(diff, [hid])
        self.assertFalse(os.path.exists(self._zh_path() + ".tmp"))

    def test_seed_writes_temp_file(self):
        before = self._zh()
        hid = next(iter(before))
        status, body = self._post("/api/seed", {
            "lang": "zh", "id": hid, "text": "seed 改过"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("ok"))
        after = self._zh()
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[hid], "seed 改过")

    def test_zz_repo_files_untouched(self):
        changed = [p for p, d in self.repo_digests.items()
                   if _digest(p) != d]
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
