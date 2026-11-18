# -*- coding: utf-8 -*-
"""build_time.py —— 构建时间来源，一处决定“哪个时间”。

默认取当前 UTC 时间；设置 ``SOURCE_DATE_EPOCH`` 时一切与时间有关的输出都用它：

- zip 条目的 mtime（同一 commit 重建出的包逐字节相同）；
- ``manifest.build.at``。

tag 构建、CI 复算校验和时把 ``SOURCE_DATE_EPOCH`` 设成提交时间即可复现。
"""

import datetime
import os

MIN_ZIP_YEAR = 1980


def epoch():
    """返回 SOURCE_DATE_EPOCH（秒）；未设置或非法时返回 None。"""
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if not raw:
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def utc_timestamp(value=None):
    """``YYYY-MM-DDTHH:MM:SSZ``；value 为 None 时用 SOURCE_DATE_EPOCH 或当前时间。"""
    stamp = epoch() if value is None else value
    moment = (now_utc() if stamp is None else
              datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc))
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def zip_date_time():
    """zip 条目用的 (Y, M, D, h, m, s)，早于 1980 的一律夹到 1980-01-01。"""
    stamp = epoch()
    if stamp is None:
        return None
    moment = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc)
    if moment.year < MIN_ZIP_YEAR:
        return (MIN_ZIP_YEAR, 1, 1, 0, 0, 0)
    return (moment.year, moment.month, moment.day,
            moment.hour, moment.minute, moment.second)
