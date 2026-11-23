#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量补齐历史数据：从 2012-01-01 到今天，按年份打包成 JSON。

数据源融合：
  - 2012-01-01 ~ 2016-02-02：tricrystal 存档快照（央视官方历史文字稿快照）
  - 2016-02-03 ~ 今天：央视官方 tv.cctv.com 接口

产物（输出到 out_dir）：
  years/YYYY.json          每年的全部期次数组
  index.json               年份索引 + 总期数
  latest.json              最新一天数据（App 首屏）

用法：
  python build_history.py --out docs/data --from 2012 --workers 8
  python build_history.py --out docs/data --from 2012 --year 2015   # 只补某年
"""

import argparse
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import cctv_fetcher
import archive_fetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("build")

# 官方接口启用日期（含）之后走官方，之前走存档
OFFICIAL_FROM = 20160203

# 每期的抓取（模块级函数，便于线程池调用）
def fetch_one(date_str: str):
    key = int(date_str)
    try:
        if key >= OFFICIAL_FROM:
            return cctv_fetcher.fetch_day(date_str)
        else:
            return archive_fetcher.fetch_archive_day(date_str)
    except Exception as exc:  # noqa: BLE001
        log.warning("%s 抓取异常: %s", date_str, exc)
        return None


def daterange(year: int):
    """某年所有日期 YYYYMMDD（只到今天）。"""
    today = date.today()
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today)
    cur = start
    while cur <= end:
        yield cur.strftime("%Y%m%d")
        cur += timedelta(days=1)


def build_year(year: int, out_dir: str, workers: int):
    dates = list(daterange(year))
    log.info("开始补齐 %d 年，共 %d 天", year, len(dates))
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fmap = {ex.submit(fetch_one, d): d for d in dates}
        done = 0
        for fut in as_completed(fmap):
            d = fmap[fut]
            data = fut.result()
            done += 1
            if data:
                results[d] = data
            if done % 50 == 0 or done == len(dates):
                log.info("  %d 年进度 %d/%d，成功 %d", year, done, len(dates), len(results))

    # 按日期排序
    ordered = [results[d] for d in sorted(results)]
    os.makedirs(os.path.join(out_dir, "years"), exist_ok=True)
    out_path = os.path.join(out_dir, "years", f"{year}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"year": year, "days": len(ordered), "data": ordered}, f,
                  ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(out_path) / 1024 / 1024
    log.info("✓ %d 年完成：%d/%d 天，%d 条，%.2f MB -> %s",
             year, len(ordered), len(dates),
             sum(d["count"] for d in ordered), size, out_path)
    return len(ordered), len(dates)


def write_index(out_dir: str, years):
    total_days = sum(d for d, _ in years)
    idx = {
        "title": "新闻联播文字稿历史库",
        "years": [y for y, _ in sorted(years)],
        "total_days": total_days,
        "source": "央视网官方 + 历史存档快照",
    }
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    log.info("索引已写入，共 %d 个年份 %d 天", len(years), total_days)


def main():
    parser = argparse.ArgumentParser(description="批量补齐新闻联播历史数据")
    parser.add_argument("--out", default="docs/data", help="输出目录")
    parser.add_argument("--from", dest="year_from", type=int, default=2012, help="起始年份")
    parser.add_argument("--year", type=int, help="只补齐指定年份")
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    args = parser.parse_args()

    if args.year:
        years = [args.year]
    else:
        years = list(range(args.year_from, date.today().year + 1))

    results = []
    for y in years:
        ok, total = build_year(y, args.out, args.workers)
        results.append((y, ok))

    write_index(args.out, results)


if __name__ == "__main__":
    main()
