#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公安部新闻抓取器 —— 抓取公安部官网「公安要闻」栏目。

公安部全站启用了加速乐(__jsl_clearance_s)的 JS cookie 反爬，普通 requests
拿到的是 521 挑战页，因此这里用 Playwright 无头浏览器自动执行 JS 过校验，
再解析列表页 + 详情页，输出结构化 JSON 供 App 与微信推送使用。

用法：
    python mps_fetcher.py                 # 抓首页列表 + 详情，写入 docs/mps/latest.json
    python mps_fetcher.py --pages 3       # 抓最新 3 页
    python mps_fetcher.py --out /path.json
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

LIST_URL = "https://www.mps.gov.cn/n2253534/n2253535/index.html"
PAGE_TMPL = "https://www.mps.gov.cn/n2253534/n2253535/index_10123465_{n}.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _pw():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        sys.stderr.write("缺少 playwright，请先执行：\n"
                         "  pip install playwright && python -m playwright install chromium\n")
        raise


def fetch_html(page, url, retries=5, wait_ms=1500):
    """复用同一个 page 打开 url，自动过挑战，返回真实 HTML 或 None。"""
    for _ in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        html = ""
        try:
            html = page.content()
        except Exception:
            pass
        if "var _0x" not in html and "jsl_clearance" not in html and len(html) > 5000:
            return html
    return None


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "content.html" not in href:
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 6:
            continue
        parent = a.parent.get_text(" ", strip=True) if a.parent else ""
        m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", parent)
        date = m.group(0).replace("-", "") if m else ""
        url = urljoin(base_url, href)
        if url not in out:
            out[url] = {"title": title, "date": date, "url": url}
    return list(out.values())


def parse_detail(html, url):
    soup = BeautifulSoup(html, "html.parser")
    t = soup.select_one(".bTitle p") or soup.select_one("h1")
    title = t.get_text(" ", strip=True) if t else ""
    word = soup.select_one(".wordContent")
    content = word.get_text("\n", strip=True) if word else ""
    source = ""
    tm = soup.select_one(".banner .time")
    if tm:
        ms = re.search(r"来源[：:]\s*([^\s　]+)", tm.get_text(" ", strip=True))
        if ms:
            source = ms.group(1)
    return {"title": title, "source": source, "content": content, "url": url}


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


def scrape(pages=1, out_path=None):
    sync_playwright = _pw()
    result = {"source": "公安部·公安要闻",
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "count": 0, "news": []}

    # 先读入历史，抓取时按 url 合并（新的覆盖旧的，历史独有项保留）
    history = load_history(out_path)

    def flush(news):
        merged = dict(history)                     # 历史打底
        for n in news:                             # 本次抓取覆盖同名 url
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

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=UA, locale="zh-CN")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()   # 全程复用同一个 page，cookie 自然继承

        items = {}
        list_urls = [LIST_URL] + [PAGE_TMPL.format(n=n) for n in range(1, pages)]
        for lu in list_urls:
            h = fetch_html(page, lu)
            if not h:
                sys.stderr.write(f"[warn] 列表页失败: {lu}\n")
                continue
            for it in parse_list(h, lu):
                items.setdefault(it["url"], it)
            sys.stderr.write(f"[info] 列表: 累计 {len(items)} 条\n")

        news = []
        # 只保留带 YYYYMMDD 日期的条目，过滤"办事指南"等非新闻干扰项
        ordered = [it for it in items.values() if re.fullmatch(r"20\d{6}", it["date"])]
        ordered.sort(key=lambda x: x["date"], reverse=True)
        for i, it in enumerate(ordered):
            h = fetch_html(page, it["url"])
            if not h:
                sys.stderr.write(f"[warn] 详情失败: {it['url']}\n")
                continue
            d = parse_detail(h, it["url"])
            if not d["content"]:
                continue
            d["date"] = it["date"]
            d["title"] = d["title"] or it["title"]
            news.append(d)
            flush(news)
            sys.stderr.write(f"[info] ({i+1}/{len(ordered)}) {d['date']} {d['title'][:28]}\n")
            time.sleep(0.3)
        browser.close()

    news.sort(key=lambda x: (x.get("date", ""), x.get("title", "")), reverse=True)
    flush(news)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="抓取列表页数（含首页），默认1")
    ap.add_argument("--out", default="docs/mps/latest.json", help="输出 JSON 路径")
    args = ap.parse_args()

    data = scrape(pages=args.pages, out_path=args.out)
    print(f"完成: {args.out} 共 {data['count']} 条")


if __name__ == "__main__":
    main()
