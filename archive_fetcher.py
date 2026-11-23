#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据抓取（2012 ~ 2016-02）：读取 tricrystal/CCTV-News-article 存档快照。
该存档是央视官方文字稿在页面失效前被保存下来的历史快照，本质仍是官方数据。

Markdown 格式：
  ---
  layout: "default"
  title: "新闻联播文字稿（2015年6月15日）"
  ---
  # 新闻联播文字稿 · 2015年6月15日
  > 共 14 条新闻 ...
  ## [视频]标题一
  正文段落...
  ## [视频]标题二
  正文段落...
"""

import logging
import re
from datetime import datetime

import requests

log = logging.getLogger("archive_fetcher")

BASE = "https://raw.githubusercontent.com/tricrystal/CCTV-News-article/main/{year}/%E6%96%B0%E9%97%BB%E8%81%94%E6%92%AD_{date}.md"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


def fetch_archive_day(date_str: str, retries: int = 2):
    """读取某天的存档快照，返回与 cctv_fetcher.fetch_day 相同结构的数据。"""
    year = date_str[:4]
    url = BASE.format(year=year, date=date_str)
    text = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                r.encoding = "utf-8"
                text = r.text
                break
            if r.status_code == 404:
                return None
        except Exception as exc:  # noqa: BLE001
            if attempt < retries:
                import time
                time.sleep(0.6 * attempt)
    if not text:
        return None

    return parse_archive_md(date_str, text)


def parse_archive_md(date_str: str, text: str):
    """解析存档 Markdown 为结构化数据。"""
    # 按 "## " 切分条目
    parts = re.split(r"^##\s+", text, flags=re.M)
    news = []
    missing = 0
    for part in parts[1:]:  # 第一部分是 YAML + 标题头
        lines = part.split("\n", 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""
        title = re.sub(r"^\[视频\]\s*", "", title)
        if "完整版" in title or not title:
            continue
        # 去掉存档内的导航链接行
        body = re.sub(r"^>.*$", "", body, flags=re.M)
        body = re.sub(r"varpara_count=\d+", "", body)
        body = re.sub(r"[ \t]+$", "", body, flags=re.M)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        if "正文缺失" in body and len(body) < 40:
            missing += 1
            content = "（该期正文已失效，仅存标题）"
        elif not body:
            missing += 1
            content = "（该期正文已失效，仅存标题）"
        else:
            content = body

        news.append({
            "index": len(news) + 1,
            "title": title,
            "content": content,
            "url": "",
        })

    if not news:
        return None
    return {
        "date": date_str,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(news),
        "partial": missing > 0,
        "failed_count": missing,
        "source": "archive",
        "news": news,
    }


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "20150615"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = fetch_archive_day(d)
    if data:
        print(f"{d}: {data['count']} 条, 缺失 {data['failed_count']} 条")
        for n in data["news"][:3]:
            print("  -", n["title"][:40], "| 正文", len(n["content"]), "字")
    else:
        print("无数据")
