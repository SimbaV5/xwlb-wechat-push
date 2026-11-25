#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
党建每日学 Word 文档生成器
=====================================================================
每天新闻联播抓取完成后调用，取当天新闻联播【第一条】内容生成一期文档：

  第 1 行：居中、红色、二号字体「训练中心党建每日学」
  第 2 行：居中、仿宋、三号字体「第 X 期」（X = 当天是全年的第几天）
  第 3 行：居中、仿宋、小三字体，当天日期（2026年11月24日 星期三）
  其  后：当天新闻联播第一条的标题 + 正文

输出：
  docs/dangjian/党建每日学_第X期_YYYYMMDD.docx   按日期存档
  docs/dangjian/latest.docx                      始终指向最新一期（供 App/下载页取用）

也支持命令行指定日期：python dangjian_docx.py --date 20261124
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

CST = timezone(timedelta(hours=8))
OUT = "docs/dangjian"
DATA = "docs/data"

WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def set_font(run, cn_font, size_pt, bold=False, color=None):
    """同时设置中英文字体（eastAsia 必须单独设置才对中文生效）、字号、加粗、颜色。"""
    run.font.name = cn_font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), cn_font)
    rfonts.set(qn("w:ascii"), cn_font)
    rfonts.set(qn("w:hAnsi"), cn_font)
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def load_day(date_str):
    """从 latest.json 或 years/YYYY.json 里取某天的新闻包。"""
    # 先试 latest
    lp = os.path.join(DATA, "latest.json")
    if os.path.exists(lp):
        try:
            d = json.load(open(lp, encoding="utf-8"))
            if d.get("date") == date_str and d.get("news"):
                return d
        except Exception:  # noqa: BLE001
            pass
    # 再试年份包
    yp = os.path.join(DATA, "years", date_str[:4] + ".json")
    if os.path.exists(yp):
        d = json.load(open(yp, encoding="utf-8"))
        for day in d.get("data", []):
            if day.get("date") == date_str:
                return day
    return None


def build_docx(date_str, day_data):
    dt = datetime.strptime(date_str, "%Y%m%d")
    yday = dt.timetuple().tm_yday          # 全年第几天
    date_cn = f"{dt.year}年{dt.month}月{dt.day}日 {WEEK[dt.weekday()]}"

    doc = Document()

    # ---- 第 1 行：居中、红色、二号「训练中心党建每日学」----
    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run("训练中心党建每日学")
    set_font(r1, "方正小标宋简体", 22, bold=True, color=(0xC0, 0x00, 0x00))  # 二号=22pt

    # ---- 第 2 行：居中、仿宋、三号「第 X 期」----
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(f"第 {yday} 期")
    set_font(r2, "仿宋", 16)  # 三号=16pt

    # ---- 第 3 行：居中、仿宋、小三、当天日期 ----
    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r3 = p3.add_run(date_cn)
    set_font(r3, "仿宋", 15)  # 小三=15pt

    # 空行分隔
    doc.add_paragraph()

    # ---- 正文：当天新闻联播第一条 ----
    news = day_data.get("news", [])
    if news:
        first = news[0]
        # 标题：仿宋三号加粗
        pt = doc.add_paragraph()
        pt.alignment = WD_ALIGN_PARAGRAPH.LEFT
        rt = pt.add_run(first.get("title", ""))
        set_font(rt, "仿宋", 16, bold=True)
        # 正文段落
        content = first.get("content", "")
        for para in content.split("\n"):
            para = para.strip()
            if not para:
                continue
            pb = doc.add_paragraph()
            pb.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            pf = pb.paragraph_format
            pf.first_line_indent = Pt(32)  # 首行缩进 2 字符（三号16pt×2）
            pf.line_spacing = 1.5
            rb = pb.add_run(para)
            set_font(rb, "仿宋", 16)

    return doc, yday


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="指定日期 YYYYMMDD，默认北京时间当天")
    ap.add_argument("--fallback", action="store_true", help="当天无数据时向前回退最多7天")
    args = ap.parse_args()

    date_str = args.date.replace("-", "") or datetime.now(CST).strftime("%Y%m%d")
    day_data = load_day(date_str)

    if not day_data and args.fallback:
        base = datetime.strptime(date_str, "%Y%m%d")
        for back in range(1, 8):
            cand = (base - timedelta(days=back)).strftime("%Y%m%d")
            day_data = load_day(cand)
            if day_data:
                print(f"{date_str} 无数据，回退到 {cand}")
                date_str = cand
                break

    if not day_data:
        print(f"{date_str} 无新闻数据，跳过文档生成")
        return

    os.makedirs(OUT, exist_ok=True)
    doc, yday = build_docx(date_str, day_data)

    archive_name = f"党建每日学_第{yday}期_{date_str}.docx"
    archive_path = os.path.join(OUT, archive_name)
    doc.save(archive_path)

    # latest.docx 始终指向最新一期
    latest_path = os.path.join(OUT, "latest.docx")
    doc.save(latest_path)

    print(f"✅ 已生成第 {yday} 期（{date_str}）: {archive_name}")
    print(f"   标题: {day_data['news'][0]['title'][:40] if day_data.get('news') else '-'}")
    print(f"   latest.docx 已更新")


if __name__ == "__main__":
    main()
