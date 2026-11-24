#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日常增量更新（修复版）：
  1) 用【北京时间】决定目标日期（GitHub Actions runner 是 UTC，直接用 datetime.now()
     会在凌晨把“今天”算成前一天，导致 24 号抓成 23 号 —— 这是日期滞后的根因之一）
  2) 当天文字稿未上线时自动向前回退，找最近有数据的一天写入 latest.json
  3) 每次运行补偿【最近 LOOKBACK_DAYS 天】缺失的日期，保证某天定时任务没跑也能自愈补齐
  4) 同步更新公安部新闻（失败不影响主流程）
供 GitHub Actions 每天定时调用，也支持 workflow_dispatch / 本地直接运行。
"""
import json
import os
from datetime import datetime, timedelta, timezone

import cctv_fetcher
import archive_fetcher

CST = timezone(timedelta(hours=8))
OUT = "docs/data"
OFFICIAL_FROM = 20160203
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "5"))  # 补偿窗口天数（含当天）


def fetch_one(d):
    """抓某一天，返回 data dict 或 None（不抛异常）。"""
    try:
        fetcher = cctv_fetcher if int(d) >= OFFICIAL_FROM else archive_fetcher
        fn = getattr(fetcher, "fetch_day", None) or getattr(fetcher, "fetch_archive_day", None)
        if fn is None:
            return None
        return fn(d)
    except Exception as exc:  # noqa: BLE001
        print(f"抓取 {d} 异常: {exc}")
        return None


def load_year(year):
    """读取年份数据包，返回 {year, days, data:[{date,...}]}。"""
    ypath = os.path.join(OUT, "years", f"{year}.json")
    if os.path.exists(ypath):
        try:
            return json.load(open(ypath, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"year": int(year), "days": 0, "data": []}


def merge_year(year, data):
    """把某天数据合并进年份包（按 date 去重），写回磁盘。"""
    root = load_year(year)
    others = [x for x in root["data"] if x.get("date") != data["date"]]
    others.append(data)
    others.sort(key=lambda x: x["date"])
    root["data"] = others
    root["days"] = len(others)
    root["year"] = int(year)
    ypath = os.path.join(OUT, "years", f"{year}.json")
    os.makedirs(os.path.dirname(ypath), exist_ok=True)
    with open(ypath, "w", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False, separators=(",", ":"))
    return root


def main():
    env = os.getenv("TARGET_DATE", "").strip().replace("-", "")
    # 关键修复：北京时间，而不是 runner 本地(UTC)时间
    today = env or datetime.now(CST).strftime("%Y%m%d")
    base = datetime.strptime(today, "%Y%m%d")
    print(f"目标日期(北京时间): {today}  补偿窗口: 最近 {LOOKBACK_DAYS} 天")

    os.makedirs(OUT, exist_ok=True)

    # ---- 1) 补偿：最近 N 天里，年份包缺失的日期全部抓回来 ----
    for back in range(LOOKBACK_DAYS - 1, -1, -1):
        d = (base - timedelta(days=back)).strftime("%Y%m%d")
        year = d[:4]
        root = load_year(year)
        if any(x.get("date") == d for x in root["data"]):
            print(f"  {d} 已在年份包中，跳过")
            continue
        data = fetch_one(d)
        if data:
            merge_year(year, data)
            print(f"  ✅ 补偿抓取 {d}: {data['count']} 条")
        else:
            print(f"  ⚠️ {d} 暂无文字稿（通常因当天尚未上线），已跳过")

    # ---- 2) latest.json 指向最近有数据的一天（从今天往前找） ----
    latest = None
    for back in range(0, 10):
        d = (base - timedelta(days=back)).strftime("%Y%m%d")
        year = d[:4]
        root = load_year(year)
        hit = next((x for x in root["data"] if x.get("date") == d), None)
        if hit:
            latest = hit
            if back > 0:
                # 尝试现场再抓一次当天（可能刚上线），成功则更新
                fresh = fetch_one(d)
                if fresh:
                    merge_year(year, fresh)
                    latest = fresh
            break

    if latest is None:
        print("近 10 天均无数据，latest.json 保持不变")
    else:
        with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, separators=(",", ":"))
        print(f"📌 latest.json 已更新为 {latest['date']}: {latest['count']} 条 "
              f"(更新于 {latest.get('updated_at', '-')})")

    # ---- 3) 公安部新闻（失败不影响主流程） ----
    try:
        update_mps()
    except Exception as e:  # noqa: BLE001
        print(f"公安部新闻更新失败（已跳过）: {e}")


def update_mps():
    """抓取公安部公安要闻，合并历史后写入 docs/mps/latest.json（增量累积）。"""
    import mps_fetcher
    mdir = os.path.join(OUT, "mps")
    os.makedirs(mdir, exist_ok=True)
    out = os.path.join(mdir, "latest.json")
    data = mps_fetcher.scrape(pages=1, out_path=out)
    print(f"已更新公安部新闻: 本地累计 {data['count']} 条")


if __name__ == "__main__":
    main()
