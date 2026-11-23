#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补抓缺失日期：低并发重试，合并回已有年份 JSON。"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import cctv_fetcher
import archive_fetcher

OFFICIAL_FROM = 20160203
OUT = "docs/data"


def fetch_one(ds):
    """官方优先，失败自动降级到存档快照（存档覆盖 2002 至今，稳定）。"""
    data = None
    try:
        if int(ds) >= OFFICIAL_FROM:
            data = cctv_fetcher.fetch_day(ds)
        else:
            data = archive_fetcher.fetch_archive_day(ds)
    except Exception:
        pass
    if not data:
        try:
            data = archive_fetcher.fetch_archive_day(ds)
        except Exception:
            pass
    return ds, data


def repair_year(year):
    path = os.path.join(OUT, "years", f"{year}.json")
    root = json.load(open(path, encoding="utf-8"))
    existing = {x["date"] for x in root["data"]}

    cur = date(year, 1, 1)
    end = min(date(year, 12, 31), date.today())
    missing = []
    while cur <= end:
        ds = cur.strftime("%Y%m%d")
        if ds not in existing:
            missing.append(ds)
        cur += timedelta(days=1)

    if not missing:
        print(f"{year}: 无缺失")
        return
    print(f"{year}: 缺失 {len(missing)} 天，开始低并发补抓…")

    got = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        fmap = {ex.submit(fetch_one, ds): ds for ds in missing}
        done = 0
        for fut in as_completed(fmap):
            ds, data = fut.result()
            done += 1
            if data:
                got[ds] = data
            if done % 30 == 0:
                print(f"  进度 {done}/{len(missing)}，成功 {len(got)}")

    # 合并并按日期排序
    for ds, data in got.items():
        root["data"].append(data)
    root["data"].sort(key=lambda x: x["date"])
    root["days"] = len(root["data"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ {year}: 补回 {len(got)}/{len(missing)} 天，现有 {root['days']} 天")


if __name__ == "__main__":
    years = [int(y) for y in sys.argv[1:]] or [2016, 2021, 2022]
    for y in years:
        repair_year(y)
