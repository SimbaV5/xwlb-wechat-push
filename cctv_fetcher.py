#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
央视网《新闻联播》全年代官方抓取器
=====================================================================
根据日期自动选择央视官方对应年代的域名与编码：

  2009-06-25 ~ 2010-05-06  news.cctv.com/program/xwlb/YYYYMMDD.shtml     (GBK)
  2010-05-06 ~ 2011-04-06  news.cntv.cn/program/xwlb/YYYYMMDD.shtml      (GBK)
  2011-04-06 ~ 2016-02-03  cctv.cntv.cn/lm/xinwenlianbo/YYYYMMDD.shtml   (GBK)
  2016-02-03 ~ 至今         tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml        (UTF-8)

旧版列表页用 JS 数组存标题与详情链接：
  item_01[i] = new title_array_01('标题', '详情页URL');
旧版详情页正文在 <div id="content_body"> 内。
新版列表页用 <li><a href=...>，详情页正文在 <div id="content_area"> 内。

支持部分详情页失效时跳过，不中断整期。
"""

import logging
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("cctv_fetcher")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}

# 分段边界（用 YYYYMMDD 整数比较）
SEGMENTS = [
    (20090625, 20100506, "http://news.cctv.com/program/xwlb/{d}.shtml", "gbk"),
    (20100506, 20110406, "http://news.cntv.cn/program/xwlb/{d}.shtml", "gbk"),
    (20110406, 20160203, "http://cctv.cntv.cn/lm/xinwenlianbo/{d}.shtml", "gbk"),
    (20160203, 20991231, "https://tv.cctv.com/lm/xwlb/day/{d}.shtml", "utf-8"),
]

# 旧版详情页里“完整版视频”要跳过
SKIP_TITLE_KEYS = ("完整版",)

session = requests.Session()
session.headers.update(HEADERS)


def pick_source(date_str: str):
    """返回 (列表页URL模板, 编码, 是否新版)。"""
    key = int(date_str)
    for lo, hi, tpl, enc in SEGMENTS:
        if lo <= key < hi:
            return tpl, enc, key >= 20160203
    return None


def fetch_text(url: str, encoding: str, retries: int = 3, timeout: int = 20):
    """获取并解码页面文本；失败重试。"""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            r.encoding = encoding
            return r.text
        except Exception as exc:  # noqa: BLE001
            if attempt < retries:
                time.sleep(0.8 * attempt)
    return None


# ---------- 新版（2016-02 起）----------
def parse_new_list(html: str):
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"tv\.cctv\.com/\d{4}/\d{2}/\d{2}/[A-Za-z0-9_]+\.shtml", href):
            continue
        title = (a.get("title") or a.get_text(strip=True) or "").strip()
        if not title:
            continue
        if "《新闻联播》" in title and "[视频]" not in title:
            continue  # 整期完整版
        title = re.sub(r"^\[视频\]\s*", "", title)
        if href in seen:
            continue
        seen.add(href)
        items.append((title, href))
    return items


def parse_new_detail(html: str):
    soup = BeautifulSoup(html, "html.parser")
    area = soup.find(id="content_area")
    if not area:
        return None
    paras = [p.get_text(strip=True) for p in area.find_all("p")]
    content = "\n".join(p for p in paras if p).strip()
    return content or None


# ---------- 旧版（2009 ~ 2016-02）----------
def parse_old_list(html: str, date_str: str):
    """
    从旧版列表页提取 (标题, 详情页URL)。
    旧版有两种结构：
      A) 2011-04 ~ 2013-07：JS 数组 item_XX[n]=new title_array_XX('标题','链接')
      B) 2013-07 ~ 2016-02：普通 <a href=news.cntv.cn/YYYY/MM/DD/VIDE....shtml>
    """
    items = []
    seen = set()

    # 结构 A：JS 数组
    pattern = re.compile(
        r"item_\d+\s*\[\s*\d+\s*\]\s*=\s*new\s+title_array_\d+\s*\(\s*['\"](.*?)['\"]\s*,\s*['\"](.*?)['\"]\s*\)",
        re.S,
    )
    for title, url in pattern.findall(html):
        title = re.sub(r"^\[视频\]\s*", "", title.strip())
        if not title or any(k in title for k in SKIP_TITLE_KEYS):
            continue
        if url.startswith("//"):
            url = "http:" + url
        if url not in seen:
            seen.add(url)
            items.append((title, url))

    # 结构 B：普通 HTML 链接（VIDE 开头的新闻详情页）
    if not items:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.search(r"news\.cntv\.cn/\d{4}/\d{2}/\d{2}/VIDE[A-Za-z0-9]+\.shtml", href):
                continue
            title = (a.get("title") or a.get_text(strip=True) or "").strip()
            title = re.sub(r"^\[视频\]\s*", "", title)
            if not title or "完整版" in title:
                continue
            if href.startswith("//"):
                href = "http:" + href
            if href not in seen:
                seen.add(href)
                items.append((title, href))
    return items


def parse_old_detail(html: str):
    soup = BeautifulSoup(html, "html.parser")
    area = soup.find(id="content_body")
    if not area:
        return None
    text = area.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


# ---------- 统一入口 ----------
def fetch_day(date_str: str, max_fail_ratio: float = 0.5):
    """
    抓取某天全部新闻，返回 dict：
      {date, count, news:[{index,title,content,url}], partial:bool}
    若列表页取不到返回 None。部分详情失效则跳过并标记 partial。
    """
    src = pick_source(date_str)
    if not src:
        log.warning("%s 无对应官方接口（早于2009-06-25）", date_str)
        return None
    tpl, enc, is_new = src
    list_url = tpl.format(d=date_str)
    list_html = fetch_text(list_url, enc)
    if not list_html:
        log.warning("列表页获取失败：%s", list_url)
        return None

    items = parse_new_list(list_html) if is_new else parse_old_list(list_html, date_str)
    if not items:
        log.warning("%s 列表为空：%s", date_str, list_url)
        return None

    results, failed = [], 0
    for idx, (title, url) in enumerate(items, 1):
        detail_html = fetch_text(url, enc, retries=2, timeout=15)
        content = None
        if detail_html:
            content = parse_new_detail(detail_html) if is_new else parse_old_detail(detail_html)
        if content:
            results.append({
                "index": len(results) + 1,
                "title": title,
                "content": content,
                "url": url,
            })
        else:
            failed += 1
            log.debug("正文缺失，跳过：%s", title)

    if not results:
        return None
    return {
        "date": date_str,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(results),
        "partial": failed > 0,
        "failed_count": failed,
        "news": results,
    }


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = fetch_day(d)
    if data:
        print(f"{d}: {data['count']} 条, 缺失 {data['failed_count']} 条")
        for n in data["news"][:3]:
            print("  -", n["title"], "| 正文", len(n["content"]), "字")
    else:
        print("无数据")
