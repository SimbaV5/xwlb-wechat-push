#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据服务：把每天的新闻联播文字稿生成为结构化 JSON，供 Android App 读取。

产物（输出到 docs/ 目录，可直接作为 GitHub Pages 站点根目录）：
    docs/index.json              日期索引，列出所有可用日期
    docs/latest.json             最新一天的完整数据（App 启动快速加载）
    docs/data/YYYYMMDD.json      某一天的完整数据

它与 main.py（微信推送）复用同一套抓取函数，可独立运行，也可在
GitHub Actions 中每天定时与推送一起执行。

用法：
    python generate_json.py                    # 生成当天数据
    python generate_json.py --date 20251117    # 指定日期
    python generate_json.py --date 20251117 --days 7   # 生成最近 7 天
    python generate_json.py --out docs         # 指定输出目录（默认 docs）
"""

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone

# 复用 main.py 中经过验证的抓取函数
from main import (
    CST,
    fetch_all_articles,
    fetch_news_list,
    get_session,
    resolve_target_date,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("xwlb-json")


def write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("已写入 %s", path)


def generate(date_str: str, out_dir: str, days: int) -> None:
    session = get_session()

    # 确定要生成的日期列表（可从今天往前回溯 days 天）
    base = datetime.strptime(date_str, "%Y%m%d")
    dates = [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

    available = []
    latest_data = None
    for d in dates:
        items = fetch_news_list(session, d)
        if not items:
            log.warning("%s 无数据，跳过", d)
            continue
        articles = fetch_all_articles(items, max_workers=5)
        if not articles:
            log.warning("%s 无正文，跳过", d)
            continue

        # 组装 news（此处重新带上 url）
        news_list = []
        url_map = dict(items)
        for idx, (title, content) in enumerate(articles, 1):
            news_list.append({
                "index": idx,
                "title": title,
                "content": content,
                "url": url_map.get(title, ""),
            })
        day_data = {
            "date": d,
            "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(news_list),
            "news": news_list,
        }
        write_json(os.path.join(out_dir, "data", f"{d}.json"), day_data)
        available.append(d)
        if latest_data is None:
            latest_data = day_data

    if not available:
        log.error("未生成任何数据文件")
        return

    # 写索引（按日期倒序）
    index_data = {
        "title": "新闻联播文字稿",
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "dates": sorted(available, reverse=True),
    }
    write_json(os.path.join(out_dir, "index.json"), index_data)
    write_json(os.path.join(out_dir, "latest.json"), latest_data)
    log.info("完成：共 %d 天数据，最新日期 %s", len(available), available[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="生成新闻联播 JSON 数据服务")
    parser.add_argument("--date", help="起始日期 YYYYMMDD（默认北京时间当天）")
    parser.add_argument("--days", type=int, default=1, help="生成最近 N 天（默认 1）")
    parser.add_argument("--out", default="docs", help="输出目录（默认 docs）")
    args = parser.parse_args()

    date_str = resolve_target_date(args.date)
    generate(date_str, args.out, max(1, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
