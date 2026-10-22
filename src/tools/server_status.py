#!/usr/bin/env python3
# coding: utf-8
r"""server_status.py —— 看看编辑器后端现在有几个实例、都是谁。

    python src/tools/server_status.py          # 列出 8777–8800 上的编辑器
    python src/tools/server_status.py --stop 8779   # 停掉某个端口上的实例

不依赖启动器：直接问每个端口的 /api/health，所以旧版本的服务也认得出。
"""

import argparse
import json
import os
import sys
import time
import urllib.request

BASE = 8777
TRIES = 24


def health(port, timeout=0.3):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % port, timeout=timeout) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        return info if isinstance(info, dict) and info.get("app") == "pr2-editor" else None
    except Exception:
        return None


def fmt_uptime(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return "?"
    if sec < 60:
        return "%d 秒" % sec
    m = sec // 60
    if m < 60:
        return "%d 分钟" % m
    return "%d 小时 %d 分" % (m // 60, m % 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", type=int, default=0, help="停掉这个端口上的实例")
    ap.add_argument("--base", type=int, default=BASE)
    args = ap.parse_args()

    if args.stop:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/shutdown" % args.stop, method="POST")
            urllib.request.urlopen(req, timeout=1.5).read()
            print("已请求 %d 上的实例退出" % args.stop)
            return 0
        except Exception as exc:
            print("停止失败：%s" % exc)
            return 1

    found = 0
    for port in range(args.base, args.base + TRIES):
        info = health(port)
        if not info:
            continue
        found += 1
        print("端口 %-5d pid %-7s 启动 %s  运行 %s  python %s"
              % (port, info.get("pid", "?"),
                 time.strftime("%H:%M:%S", time.localtime(info.get("started", 0)))
                 if info.get("started") else "(未知)",
                 fmt_uptime(info.get("uptime", "?")),
                 info.get("python", "?")))
    if not found:
        print("8777–%d 上没有发现编辑器实例。" % (args.base + TRIES - 1))
        return 1
    print("\n共 %d 个实例。停掉某个：python src/tools/server_status.py --stop <端口>" % found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
