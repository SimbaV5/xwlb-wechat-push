#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中纪委国家监委通报抓取器 —— 抓取官网「要闻」栏目里的通报/审查调查/双开类新闻。

中纪委全站启用了 haplat 滑块验证码 WAF，普通 requests 拿到的是验证码页，
因此用 Playwright 无头浏览器（真实浏览器指纹可自动过校验）解析列表页+详情页，
输出结构化 JSON 供 App 浏览。

用法：
    python ccdi_fetcher.py                       # 抓首页列表+详情，写 docs/ccdi/latest.json
    python ccdi_fetcher.py --pages 2             # 抓最新2页
    python ccdi_fetcher.py --out /path.json
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

LIST_URL = "https://www.ccdi.gov.cn/yaowenn/"
PAGE_TMPL = "https://www.ccdi.gov.cn/yaowenn/index_{n}.html"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 通报类关键词：命中任一才算"通报新闻"
KEYWORDS = ("通报", "曝光", "审查调查", "接受审查", "双开", "开除党籍",
            "开除公职", "处分", "被查", "立案", "留置", "移送司法", "典型问题")


def _pw():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        sys.stderr.write("缺少 playwright，请先执行：\n"
                         "  pip install playwright && python -m playwright install chromium\n")
        raise


def fetch_html(page, url, retries=3, wait_ms=1200):
    """复用同一个 page 打开 url，自动过验证码，返回真实 HTML 或 None。"""
    for _ in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        html = ""
        try:
            html = page.content()
        except Exception:
            pass
        if "captcha" not in html.lower() and "haplat" not in html.lower() and len(html) > 5000:
            return html
    return None


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 文章链接形如 ./202611/t20261124_524003.html
        m = re.search(r"t(20\d{6})_\d+\.html", href)
        if not m:
            continue
        date = m.group(1)
        title = a.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        # 只保留通报类
        if not any(k in title for k in KEYWORDS):
            continue
        url = urljoin(base_url, href)
        if url not in out:
            out[url] = {"title": title, "date": date, "url": url}
    return list(out.values())


def parse_detail(html, url):
    soup = BeautifulSoup(html, "html.parser")
    # 标题：<title>XXX————要闻——中央纪委国家监委网站
    title = ""
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        title = re.split(r"[—\-]{2,}", raw)[0].strip()
    # 正文在 .content
    word = soup.select_one(".content")
    content = word.get_text("\n", strip=True) if word else ""
    # 日期：页面里的 2026-11-24
    date = ""
    tm = re.search(r"(20\d{2})-(\d{2})-(\d{2})", soup.get_text(" ", strip=True))
    if tm:
        date = "".join(tm.groups())
    # 来源：中央纪委国家监委网站讯 / 据XX纪委监委消息
    source = ""
    sm = re.search(r"据([^\s，。]{2,20}?纪委监委|中央纪委国家监委)", content)
    if sm:
        source = sm.group(1)
    return {"title": title, "source": source, "content": content, "date": date, "url": url}


def scrape(pages=1, out_path=None, limit=30):
    sync_playwright = _pw()
    result = {"source": "中央纪委国家监委·通报",
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "count": 0, "news": []}

    def flush(news):
        result["news"] = news
        result["count"] = len(news)
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
        page = ctx.new_page()

        items = {}
        list_urls = [LIST_URL] + [PAGE_TMPL.format(n=n) for n in range(1, pages)]
        for lu in list_urls:
            h = fetch_html(page, lu)
            if not h:
                sys.stderr.write(f"[warn] 列表页失败: {lu}\n")
                continue
            for it in parse_list(h, lu):
                items.setdefault(it["url"], it)
            sys.stderr.write(f"[info] 列表 {lu}: 累计 {len(items)} 条通报\n")

        ordered = sorted(items.values(), key=lambda x: x["date"], reverse=True)[:limit]
        news = []
        for i, it in enumerate(ordered):
            h = fetch_html(page, it["url"])
            if not h:
                sys.stderr.write(f"[warn] 详情失败: {it['url']}\n")
                continue
            d = parse_detail(h, it["url"])
            if not d["content"]:
                continue
            d["date"] = d["date"] or it["date"]
            d["title"] = d["title"] or it["title"]
            news.append(d)
            flush(news)
            sys.stderr.write(f"[info] ({i+1}/{len(ordered)}) {d['date']} {d['title'][:30]}\n")
            time.sleep(0.3)
        browser.close()

    news.sort(key=lambda x: (x.get("date", ""), x.get("title", "")), reverse=True)
    flush(news)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1, help="抓取列表页数（含首页），默认1")
    ap.add_argument("--limit", type=int, default=30, help="最多抓多少条详情，默认30")
    ap.add_argument("--out", default="docs/ccdi/latest.json", help="输出 JSON 路径")
    args = ap.parse_args()

    data = scrape(pages=args.pages, out_path=args.out, limit=args.limit)
    print(f"完成: {args.out} 共 {data['count']} 条")


if __name__ == "__main__":
    main()
