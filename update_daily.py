#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日常增量更新：抓当天数据，更新 latest.json 并合并进当年 years/YYYY.json。
供 GitHub Actions 每天定时调用，保证 App 启动增量更新能拿到最新内容。
"""
import json
import os
from datetime import datetime

import cctv_fetcher
import archive_fetcher

OUT = "docs/data"
OFFICIAL_FROM = 20160203


def main():
    today = os.getenv("TARGET_DATE", "").strip() or datetime.now().strftime("%Y%m%d")
    fetcher = cctv_fetcher if int(today) >= OFFICIAL_FROM else archive_fetcher
    data = fetcher.fetch_day(today) if hasattr(fetcher, "fetch_day") else fetcher.fetch_archive_day(today)
    if not data:
        print("当天无数据，跳过")
        return

    os.makedirs(OUT, exist_ok=True)
    # latest.json
    with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    # 合并进当年 years/YYYY.json
    year = today[:4]
    ypath = os.path.join(OUT, "years", f"{year}.json")
    root = {"year": int(year), "days": 0, "data": []}
    if os.path.exists(ypath):
        root = json.load(open(ypath, encoding="utf-8"))
    others = [x for x in root["data"] if x.get("date") != today]
    others.append(data)
    others.sort(key=lambda x: x["date"])
    root["data"] = others
    root["days"] = len(others)
    os.makedirs(os.path.dirname(ypath), exist_ok=True)
    with open(ypath, "w", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已更新 {today}: {data['count']} 条，当年共 {root['days']} 天")

    # 同步更新公安部新闻动态（失败不影响新闻联播主流程）
    try:
        update_mps()
    except Exception as e:
        print(f"公安部新闻更新失败（已跳过）: {e}")


def update_mps():
    """抓取公安部公安要闻，写入 docs/mps/latest.json。"""
    import mps_fetcher
    data = mps_fetcher.scrape(pages=1)
    mdir = os.path.join(OUT, "mps")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已更新公安部新闻: {data['count']} 条")


if __name__ == "__main__":
    main()
