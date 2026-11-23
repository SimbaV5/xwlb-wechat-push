#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日一键更新（供 WorkBuddy 定时任务调用）：
1. 抓取最近有数据的一天新闻联播（当天没发布就往前找），更新 latest.json / 当年包 / index.json
2. 抓取公安部公安要闻（失败不影响主流程，保留旧数据）
3. 把变更同步到公网发布站点 release-site/
运行完再由 auto_update.sh 调用 publish.js 重新发布。
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta

BASE = "/workspace/xwlb-wechat-push"
SITE = "/workspace/release-site"
sys.path.insert(0, BASE)

import cctv_fetcher

DATA = os.path.join(BASE, "docs", "data")
OUT = []


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    OUT.append(line)


def find_latest_with_data(max_back=4):
    """从今天往前找最近有数据的一天，返回 (日期YYYYMMDD, data)。"""
    today = datetime.now()
    for i in range(max_back):
        d = (today - timedelta(days=i)).strftime("%Y%m%d")
        try:
            data = cctv_fetcher.fetch_day(d)
        except Exception as e:
            log(f"抓取 {d} 异常: {e}")
            continue
        if data and data.get("count", 0) > 0:
            return d, data
        log(f"{d} 暂无数据，往前找…")
    return None, None


def update_xwlb():
    date, data = find_latest_with_data()
    if not data:
        log("新闻联播：近几日均无数据，保留现有数据")
        return False

    # latest.json
    with open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    # 当年包
    year = date[:4]
    ypath = os.path.join(DATA, "years", f"{year}.json")
    root = {"year": int(year), "days": 0, "data": []}
    if os.path.exists(ypath):
        root = json.load(open(ypath, encoding="utf-8"))
    others = [x for x in root["data"] if x.get("date") != date]
    others.append(data)
    others.sort(key=lambda x: x["date"])
    root["data"] = others
    root["days"] = len(others)
    os.makedirs(os.path.dirname(ypath), exist_ok=True)
    with open(ypath, "w", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False, separators=(",", ":"))

    # index.json 计数重算
    total_days = total_news = 0
    for y in range(2012, datetime.now().year + 1):
        p = os.path.join(DATA, "years", f"{y}.json")
        if os.path.exists(p):
            r = json.load(open(p, encoding="utf-8"))
            total_days += len(r["data"])
            total_news += sum(len(d.get("news", [])) for d in r["data"])
    ipath = os.path.join(DATA, "index.json")
    idx = json.load(open(ipath, encoding="utf-8"))
    idx["total_days"], idx["total_news"] = total_days, total_news
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))

    log(f"新闻联播：已更新至 {date}，{data['count']} 条；当年 {root['days']} 天，总计 {total_days} 天/{total_news} 条")
    return True


def update_mps():
    try:
        import mps_fetcher
        data = mps_fetcher.scrape(pages=1)
        mdir = os.path.join(BASE, "docs", "mps")
        os.makedirs(mdir, exist_ok=True)
        with open(os.path.join(mdir, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        log(f"公安部：已更新 {data['count']} 条")
    except Exception as e:
        log(f"公安部更新失败（保留旧数据）: {e}")


def sync_to_site():
    pairs = [
        (os.path.join(DATA, "latest.json"), os.path.join(SITE, "data", "latest.json")),
        (os.path.join(DATA, "index.json"), os.path.join(SITE, "data", "index.json")),
        (os.path.join(DATA, "years"), os.path.join(SITE, "data", "years")),
        (os.path.join(BASE, "docs", "mps", "latest.json"), os.path.join(SITE, "mps", "latest.json")),
    ]
    for src, dst in pairs:
        if not os.path.exists(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            # 只复制文件，逐年覆盖
            for fn in os.listdir(src):
                if fn.endswith(".json"):
                    shutil.copy2(os.path.join(src, fn), os.path.join(dst, fn))
        else:
            shutil.copy2(src, dst)
    log("已同步数据到公网站点目录")


def main():
    log("===== 每日更新开始 =====")
    update_xwlb()
    update_mps()
    sync_to_site()
    log("===== 每日更新结束（下一步：publish.js 重新发布） =====")


if __name__ == "__main__":
    main()
