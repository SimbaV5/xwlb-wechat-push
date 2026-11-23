#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻联播文字稿微信推送
=====================================================================
每晚定时抓取央视网当天《新闻联播》各条新闻的文字稿，整理成文本/Markdown，
通过 PushPlus 推送到微信。

数据来源：央视网电视栏目页 https://tv.cctv.com/lm/xwlb/
推送渠道：PushPlus  http://www.pushplus.plus/send

用法示例：
    # 正式运行（推送当天内容）
    python main.py

    # 本地测试：只看抓取和格式化结果，不真正推送
    python main.py --dry-run

    # 测试指定日期
    python main.py --date 20251117 --dry-run

环境变量：
    PUSHPLUS_TOKEN   必填，PushPlus 用户 token（dry-run 时可省略）
    PUSH_MAX_CHARS   选填，单条推送最大字符数，默认 12000，超出自动分段
    PUSH_TEMPLATE    选填，推送模板 markdown/txt，默认 markdown
    CCTV_FALLBACK    选填，当天无数据时是否回退最近有数据的日期，默认 1
    TARGET_DATE      选填，覆盖目标日期（YYYYMMDD），一般无需设置
"""

import argparse
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# 常量配置
# -------------------------------------------------------------------
LIST_URL = "https://tv.cctv.com/lm/xwlb/day/{date}.shtml"
PUSH_URL = "https://www.pushplus.plus/send"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 详情页链接：https://tv.cctv.com/2025/11/17/VIDE________.shtml
ARTICLE_URL_RE = re.compile(r"tv\.cctv\.com/\d{4}/\d{2}/\d{2}/[A-Za-z0-9_]+\.shtml")

# 北京时间时区（UTC+8）—— 央视网以北京时间发布，GitHub Actions 服务器多为 UTC
CST = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("xwlb")


# -------------------------------------------------------------------
# 网络请求（带重试 + 随机延迟，防反爬）
# -------------------------------------------------------------------
def get_session() -> requests.Session:
    """复用 TCP 连接的 Session。"""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch_html(session: requests.Session, url: str, retries: int = 3,
               timeout: int = 20) -> str | None:
    """GET 一个页面并返回 utf-8 文本；失败重试，全部失败返回 None。"""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001 - 网络异常类型较多，统一重试
            log.warning("请求失败(%d/%d) %s -> %s", attempt, retries, url, exc)
            if attempt < retries:
                time.sleep(1.5 * attempt + random.uniform(0, 0.8))
    return None


# -------------------------------------------------------------------
# 抓取列表页 + 详情页
# -------------------------------------------------------------------
def fetch_news_list(session: requests.Session, date_str: str):
    """
    抓取某天的新闻列表，返回 [(标题, 详情页URL), ...]。
    会跳过整期《新闻联播》完整版（那是整段视频，无单独文字稿）。
    """
    url = LIST_URL.format(date=date_str)
    html = fetch_html(session, url)
    if not html:
        log.error("无法获取新闻列表页：%s", url)
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not ARTICLE_URL_RE.search(href):
            continue
        title = (a.get("title") or a.get_text(strip=True) or "").strip()
        if not title:
            continue
        # 跳过整期完整版：标题形如 “《新闻联播》 20251117 19:00”，不含 [视频]
        if "《新闻联播》" in title and "[视频]" not in title:
            continue
        # 统一去掉 "[视频]" 前缀，让文本更干净
        title = re.sub(r"^\[视频\]\s*", "", title)
        if href in seen:
            continue
        seen.add(href)
        items.append((title, href))

    log.info("%s 共发现 %d 条新闻", date_str, len(items))
    return items


def fetch_article(session: requests.Session, item):
    """抓取单条新闻详情页正文，返回 (标题, 正文) 或 None。"""
    title, url = item
    html = fetch_html(session, url, retries=3)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    area = soup.find(id="content_area")
    if not area:
        log.warning("未找到正文区域，跳过：%s", title)
        return None
    paras = [p.get_text(strip=True) for p in area.find_all("p")]
    content = "\n".join(p for p in paras if p).strip()
    if not content:
        log.warning("正文为空，跳过：%s", title)
        return None
    return title, content


def fetch_all_articles(items, max_workers: int = 5):
    """并发抓取所有新闻正文，保持原顺序，返回 [(标题, 正文), ...]。"""
    session = get_session()
    results = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_article, session, item): idx
            for idx, item in enumerate(items)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("抓取线程异常：%s", exc)
    articles = [r for r in results if r]
    log.info("成功获取 %d/%d 条正文", len(articles), len(items))
    return articles


# -------------------------------------------------------------------
# 日期处理
# -------------------------------------------------------------------
def resolve_target_date(arg_date: str | None) -> str:
    """
    确定目标日期 YYYYMMDD：
    1) 命令行 --date 优先（仅测试用）
    2) 环境变量 TARGET_DATE
    3) 默认：北京时间当天
    """
    if arg_date:
        return arg_date.replace("-", "")
    env = os.getenv("TARGET_DATE", "").strip().replace("-", "")
    if env:
        return env
    return datetime.now(CST).strftime("%Y%m%d")


def find_date_with_data(session: requests.Session, date_str: str,
                        fallback: bool, max_lookback: int = 7):
    """
    返回 (实际使用日期, 新闻列表)。
    若目标日期无数据（例如推送过早、当天文字稿未发布），
    在 fallback 开启时向前回溯最近有数据的一天。
    """
    items = fetch_news_list(session, date_str)
    if items:
        return date_str, items
    if not fallback:
        return date_str, items

    base = datetime.strptime(date_str, "%Y%m%d")
    for back in range(1, max_lookback + 1):
        candidate = (base - timedelta(days=back)).strftime("%Y%m%d")
        log.warning("%s 暂无数据，尝试回退到 %s", date_str, candidate)
        items = fetch_news_list(session, candidate)
        if items:
            return candidate, items
    return date_str, items


# -------------------------------------------------------------------
# 格式化 + 分段
# -------------------------------------------------------------------
def pretty_date(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y%m%d")
    weekday = "一二三四五六日"[d.weekday()]
    return f"{d.year}年{d.month}月{d.day}日 星期{weekday}"


def build_markdown(date_str: str, articles, part: int = 1, total: int = 1) -> str:
    """把新闻列表整理成 Markdown 文本。"""
    header = f"# 📺 新闻联播文字稿 · {pretty_date(date_str)}"
    if total > 1:
        header += f"（第 {part}/{total} 段）"
    lines = [header, ""]
    for idx, (title, content) in enumerate(articles, 1):
        lines.append(f"## {idx}. {title}")
        lines.append("")
        lines.append(content)
        lines.append("")
    lines.append("---")
    lines.append("来源：央视网《新闻联播》· 自动整理推送")
    return "\n".join(lines)


def split_articles(articles, max_chars: int):
    """按字符数把新闻拆成多段，保证每条推送不超过 max_chars。"""
    if not articles:
        return []
    segments, current, size = [], [], 0
    for article in articles:
        length = len(article[0]) + len(article[1]) + 20  # 20 为标题序号等开销
        if current and size + length > max_chars:
            segments.append(current)
            current, size = [], 0
        current.append(article)
        size += length
    if current:
        segments.append(current)
    return segments


# -------------------------------------------------------------------
# PushPlus 推送
# -------------------------------------------------------------------
def push_to_wechat(token: str, title: str, content: str,
                   template: str = "markdown") -> bool:
    """调用 PushPlus 发送一条消息，返回是否发送成功。"""
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": template,
    }
    try:
        resp = requests.post(PUSH_URL, json=payload, timeout=20)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.error("推送请求异常：%s", exc)
        return False

    code = data.get("code")
    msg = data.get("msg", "")
    if code == 200:
        log.info("推送已提交：%s（流水号 %s）", msg, data.get("data", ""))
        return True
    log.error("推送失败：code=%s msg=%s", code, msg)
    return False


# -------------------------------------------------------------------
# 主流程
# -------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="新闻联播文字稿微信推送")
    parser.add_argument("--date", help="指定日期 YYYYMMDD 或 YYYY-MM-DD（测试用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只抓取并打印结果，不调用 PushPlus")
    parser.add_argument("--workers", type=int, default=5, help="并发抓取线程数")
    parser.add_argument("--no-fallback", action="store_true",
                        help="当天无数据时不回退到历史日期")
    args = parser.parse_args()

    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    try:
        max_chars = int(os.getenv("PUSH_MAX_CHARS", "12000"))
    except ValueError:
        max_chars = 12000
    template = os.getenv("PUSH_TEMPLATE", "markdown").strip() or "markdown"
    fallback = os.getenv("CCTV_FALLBACK", "1").strip() not in ("0", "false", "False")

    date_str = resolve_target_date(args.date)
    log.info("目标日期：%s", date_str)

    session = get_session()
    actual_date, items = find_date_with_data(session, date_str, fallback and not args.no_fallback)
    if actual_date != date_str:
        log.warning("当天无数据，实际使用日期：%s", actual_date)
    if not items:
        log.error("未获取到任何新闻，流程终止")
        return 1

    articles = fetch_all_articles(items, max_workers=args.workers)
    if not articles:
        log.error("未获取到任何正文，流程终止")
        return 1

    segments = split_articles(articles, max_chars)
    total = len(segments)
    log.info("内容共分为 %d 段推送", total)

    if args.dry_run:
        for i, seg in enumerate(segments, 1):
            md = build_markdown(actual_date, seg, i, total)
            print("\n" + "=" * 60)
            print(md)
        print("\n[dry-run] 未调用 PushPlus。")
        return 0

    if not token:
        log.error("未配置 PUSHPLUS_TOKEN，无法推送")
        return 1

    success = True
    for i, seg in enumerate(segments, 1):
        md = build_markdown(actual_date, seg, i, total)
        title = f"新闻联播 {actual_date[:4]}-{actual_date[4:6]}-{actual_date[6:]}"
        if total > 1:
            title += f" ({i}/{total})"
        if not push_to_wechat(token, title, md, template):
            success = False
        if i < total:
            time.sleep(1)  # 避免推送过快触发频率限制
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
