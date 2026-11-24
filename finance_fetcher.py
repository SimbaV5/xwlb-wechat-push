#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财经新闻抓取器 —— 抓取东方财富网财经要闻（列表 + 详情正文）。

东方财富财经频道为 utf-8、常规请求即可访问（实测详情页正文成功率极高），
无需 Playwright。抓取结果合并历史按 url 去重，输出到 docs/finance/latest.json，
供 App 财经页浏览/搜索使用。

用法：
    python finance_fetcher.py                          # 抓首页 + 要闻栏目，写 docs/finance/latest.json
    python finance_fetcher.py --pages 2 --limit 60
    python finance_fetcher.py --out /path.json
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 财经要闻列表来源（首页 + 要闻滚动栏目）
LIST_URLS = [
    "https://finance.eastmoney.com/",
    "https://finance.eastmoney.com/a/cgnjj.html",   # 国内经济
    "https://finance.eastmoney.com/a/czqyw.html",   # 证券要闻
]
ARTICLE_RE = re.compile(r"https?://finance\.eastmoney\.com/a/\d+\.html")


def fetch(url, timeout=20):
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                         timeout=timeout)
        if r.status_code != 200:
            return None
        r.encoding = "utf-8"
        return r.text
    except Exception as e:
        sys.stderr.write(f"[warn] 请求失败 {url}: {e}\n")
        return None


def parse_list(html, base_url):
    """从列表页提取 (标题, url)。"""
    out = {}
    if not html:
        return out
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = ARTICLE_RE.search(href)
        if not m:
            continue
        url = m.group(0)
        title = a.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        if url not in out or len(title) > len(out[url]):
            out[url] = title
    return out


def parse_detail(html, url, fallback_title=""):
    soup = BeautifulSoup(html or "", "html.parser")
    # 正文
    body = (soup.select_one("#ContentBody") or soup.select_one(".article-body")
            or soup.select_one(".newsContent"))
    content = body.get_text("\n", strip=True) if body else ""
    if not content:
        return None
    # 标题：优先 meta description 里的 【标题】，其次列表页兜底标题
    title = fallback_title
    md = soup.select_one('meta[name="description"]')
    if md:
        mm = re.match(r"\s*【([^】]+)】", md.get("content", ""))
        if mm:
            title = mm.group(1).strip()
    if not title:
        t = soup.select_one(".news_title") or soup.select_one("h1")
        if t:
            title = t.get_text(" ", strip=True)
    # 日期：详情页 YYYY-MM-DD
    date = ""
    dm = re.search(r"(20\d{2})-(\d{2})-(\d{2})", html or "")
    if dm:
        date = "".join(dm.groups())
    # 来源
    source = "东方财富网"
    sm = re.search(r"来源[：:]\s*([^\s　<]+)", soup.get_text(" ", strip=True))
    if sm:
        source = sm.group(1)
    return {"title": title, "source": source, "content": content,
            "date": date, "url": url}


def load_history(out_path):
    """读取已有 latest.json 里的历史条目，按 url 索引，用于增量累积。"""
    history = {}
    if not out_path or not os.path.exists(out_path):
        return history
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        for n in old.get("news", []):
            if n.get("url"):
                history[n["url"]] = n
    except Exception as e:
        sys.stderr.write(f"[warn] 读取历史失败，从零累积: {e}\n")
    return history


def scrape(pages=1, out_path=None, limit=60, list_urls=None):
    result = {"source": "财经要闻·东方财富",
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "count": 0, "news": []}

    history = load_history(out_path)

    def flush(news):
        merged = dict(history)
        for n in news:
            if n.get("url"):
                merged[n["url"]] = n
        combined = sorted(merged.values(),
                          key=lambda x: (x.get("date", ""), x.get("title", "")),
                          reverse=True)
        result["news"] = combined
        result["count"] = len(combined)
        result["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if out_path:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            tmp = out_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, out_path)

    urls = list(list_urls or LIST_URLS)
    items = {}
    for lu in urls:
        h = fetch(lu)
        got = parse_list(h, lu)
        for u, t in got.items():
            items.setdefault(u, t)
        sys.stderr.write(f"[info] 列表 {lu}: 累计 {len(items)} 条\n")

    # 按 url 中日期大致倒序（url 形如 /a/YYYYMMDDxxxx.html）
    ordered = sorted(items.items(), key=lambda kv: kv[0], reverse=True)[:limit]
    news = []
    for i, (u, title) in enumerate(ordered):
        h = fetch(u)
        d = parse_detail(h, u, fallback_title=title)
        if not d:
            continue
        news.append(d)
        flush(news)
        sys.stderr.write(f"[info] ({i+1}/{len(ordered)}) {d['date']} {d['title'][:30]}\n")
        time.sleep(0.15)
    flush(news)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="兼容参数（列表来源已内置多个栏目）")
    ap.add_argument("--limit", type=int, default=60, help="最多抓多少篇详情，默认60")
    ap.add_argument("--out", default="docs/finance/latest.json", help="输出 JSON 路径")
    args = ap.parse_args()
    data = scrape(pages=args.pages, out_path=args.out, limit=args.limit)
    print(f"完成: {args.out} 共 {data['count']} 条")


if __name__ == "__main__":
    main()
