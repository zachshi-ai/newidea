#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 left-behind 示例账本（确定性剧本，无随机，可逐字节重建）。

realistic.tsv —— 12 次行程 35 条事件，埋入已知模式（dogfood 断言的「已知答案」）：
  * 手机充电头漏带 2 次（T003 北京、T006 北京）→ 盲区，electronics 重灾区
  * 雨伞白扛 3 次（T002/L002/T005）→ 惯性悔带降级；健身裤白扛 2 次
  * 前半程漏带 5 件、后半程 2 件 → 收敛判「在改善」
  * 会议名片漏带未记价 → 不进补救账单但单独呈报
  * 补救账单 = 89+45+39+25+69+12 = ¥279
minimal.tsv —— 2 次行程 3 条事件：行程数不足，演示收敛趋势的「拒绝评估」。

运行：python3 left-behind/examples/build_examples.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent

HEADER = ["date", "trip_id", "trip_type", "days", "item", "category",
          "event", "cost", "weight_g", "notes"]

# 剧本：每行 = (date, trip_id, trip_type, days, item, category, event, cost, weight_g, notes)
SCRIPT = [
    # T001 上海：安分的一次，全勤 used（画像对照数据）
    ("2026-03-02", "T001", "business", 3, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-03-02", "T001", "business", 3, "笔记本电脑+电源", "electronics", "used", "", "", ""),
    ("2026-03-02", "T001", "business", 3, "手机充电头", "electronics", "used", "", "", ""),
    # T002 深圳：雨伞第一次白扛
    ("2026-03-18", "T002", "business", 2, "雨伞", "misc", "ghost", "", "350", "深圳没下雨"),
    ("2026-03-18", "T002", "business", 2, "手机充电线", "electronics", "used", "", "", ""),
    # T003 北京：充电头第一次漏带
    ("2026-04-08", "T003", "business", 4, "手机充电头", "electronics", "left", "89", "",
     "酒店前台借了一夜，第二天在机场补买"),
    ("2026-04-08", "T003", "business", 4, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-04-08", "T003", "business", 4, "笔记本电脑+电源", "electronics", "used", "", "", ""),
    # L001 三亚：度假账的新坑
    ("2026-04-24", "L001", "leisure", 5, "常用药", "health", "left", "45", "",
     "药店应急买的肠胃药"),
    ("2026-04-24", "L001", "leisure", 5, "防晒", "toiletries", "used", "", "", ""),
    ("2026-04-24", "L001", "leisure", 5, "健身裤", "clothes", "ghost", "", "400",
     "酒店泳池没去，裤子原样回来"),
    # T004 成都：名片漏带未记价 + 会议资料白扛
    ("2026-05-12", "T004", "business", 3, "会议名片", "misc", "left", "", "",
     "临时要用，酒店商务中心打印"),
    ("2026-05-12", "T004", "business", 3, "手机充电头", "electronics", "used", "", "", ""),
    ("2026-05-12", "T004", "business", 3, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-05-12", "T004", "business", 3, "笔记本电脑+电源", "electronics", "used", "", "", ""),
    ("2026-05-12", "T004", "business", 3, "会议资料", "misc", "ghost", "", "200",
     "客户改期，资料原样背回"),
    # L002 大理：雨伞第二次白扛，健身裤第二次白扛
    ("2026-05-28", "L002", "leisure", 4, "泳镜", "sports", "left", "39", "",
     "镇上眼镜店临时买的"),
    ("2026-05-28", "L002", "leisure", 4, "折叠衣架", "misc", "left", "25", "",
     "手洗的衣服没处晾"),
    ("2026-05-28", "L002", "leisure", 4, "雨伞", "misc", "ghost", "", "350", "大理也没下雨"),
    ("2026-05-28", "L002", "leisure", 4, "健身裤", "clothes", "ghost", "", "400",
     "又一次原样往返"),
    # T005 广州：雨伞第三次白扛——模式成立
    ("2026-06-10", "T005", "business", 2, "雨伞", "misc", "ghost", "", "350", "广州还是没下雨"),
    ("2026-06-10", "T005", "business", 2, "手机充电线", "electronics", "used", "", "", ""),
    # L003 京都：干净的一次
    ("2026-06-26", "L003", "leisure", 3, "防晒", "toiletries", "used", "", "", ""),
    ("2026-06-26", "L003", "leisure", 3, "水杯", "misc", "used", "", "", ""),
    # T006 北京：充电头第二次漏带——盲区成立；此后学乖
    ("2026-07-08", "T006", "business", 3, "手机充电头", "electronics", "left", "69", "",
     "第二次！从此充电包设常备位"),
    ("2026-07-08", "T006", "business", 3, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-07-08", "T006", "business", 3, "笔记本电脑+电源", "electronics", "used", "", "", ""),
    # L004 川西：高原的小教训
    ("2026-07-22", "L004", "leisure", 6, "创可贴", "health", "left", "12", "",
     "徒步磨脚，垭口小卖部应急"),
    ("2026-07-22", "L004", "leisure", 6, "常用药", "health", "ghost", "", "50",
     "高反药，全程没用上"),
    ("2026-07-22", "L004", "leisure", 6, "防晒", "toiletries", "used", "", "", ""),
    # T007 上海：全勤——充电头进了常备位
    ("2026-08-15", "T007", "business", 4, "手机充电头", "electronics", "used", "", "", ""),
    ("2026-08-15", "T007", "business", 4, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-08-15", "T007", "business", 4, "笔记本电脑+电源", "electronics", "used", "", "", ""),
    # L005 周边古镇：轻装短途，干净收官
    ("2026-08-29", "L005", "leisure", 2, "防晒", "toiletries", "used", "", "", ""),
    ("2026-08-29", "L005", "leisure", 2, "水杯", "misc", "used", "", "", ""),
]

MINIMAL = [
    ("2026-08-20", "M001", "business", 2, "手机充电头", "electronics", "left", "79", "",
     "临出门才发现没带"),
    ("2026-08-20", "M001", "business", 2, "手机充电线", "electronics", "used", "", "", ""),
    ("2026-09-01", "M002", "business", 3, "雨伞", "misc", "ghost", "", "350", "梅雨季过了"),
]


def write_tsv(path, rows, comment):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# %s\n" % comment)
        fh.write("\t".join(HEADER) + "\n")
        for row in rows:
            fh.write("\t".join(str(c) for c in row) + "\n")
    print("wrote %s (%d rows)" % (path, len(rows)))


def main():
    write_tsv(OUT / "realistic.tsv", SCRIPT,
              "示例错题本（确定性剧本）：12 次行程，埋入充电头盲区/雨伞三连幽灵/收敛改善")
    write_tsv(OUT / "minimal.tsv", MINIMAL,
              "最小可用账本：2 次行程——行程数不足，收敛趋势拒绝评估")


if __name__ == "__main__":
    main()
