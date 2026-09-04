#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the recoup example ledger and report snapshots.

The demo is one household's pre-move clear-out (as-of 2026-08-20):
14 listing cycles in four months. Four lots sold for ¥1,810 against
¥5,596 paid (realized ratio 32.3%); one book was given away while
still green, one moldy yoga mat went to trash, one game was pulled.

The open shelf is where the lines live:
  平板   171 days silent on an 84-day white-gift line (2x = hoarding alarm),
  显示器  a real ¥700 offer parked for 102 days (fantasy price),
  电饭锅  a ¥350 offer against a ¥330 tag (offer line: wallet knocking),
  冲锋衣  111 days silent (dead, not yet 2x),
  空气炸锅/落地灯 cooling yellow, 无人机 still green by one day.

All snapshots are rendered with an explicit --as-of: the same ledger
reproduces byte-for-byte on any machine, any clock.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "recoup.py")
AS_OF = "2026-08-20"

EVENTS = """\
# 闲置处置事件账本 · date/item/action/amount/paid/category/note
# action: list(挂出,需 paid+category) price(改价) ask(询价,amount=对方出价可空)
#         sold(成交) gave(白送/捐赠) trash(丢弃) pull(下架自留) —— 结案不填金额
date	item	action	amount	paid	category	note
2026-03-01	电纸书	list	899	1999	electronics	吃灰两年，换新款前清仓
2026-03-01	吹风机	list	150	399	appliance	高速吹风机，搬家带不动
2026-03-02	平板	list	2000	3588	electronics	换了新款，幻想卖 2000
2026-03-05	婴儿车	list	1200	2599	toy	宝宝大了，九成新
2026-03-08	人类简史	list	60	147	book	三本一起出
2026-03-10	书架	list	150	599	furniture	宜家毕利，拆好自提
2026-03-15	瑜伽垫	list	80	199	other	发霉了还是挂了挂
2026-03-15	吹风机	ask	130		联系我明天自提
2026-03-20	电纸书	price	799		一周没人看，降 100
2026-03-22	吹风机	sold	130		爽快
2026-03-25	电纸书	ask	700		能到地铁站自提吗
2026-03-28	婴儿车	price	999		降 200 试试
2026-03-29	人类简史	gave			楼下漂流角，等不及了
2026-04-01	书架	price	100		两周没动静
2026-04-02	电纸书	sold	700		28 天回血
2026-04-06	婴儿车	ask	880		能包快递吗
2026-04-12	婴儿车	ask	900		加 20 我现在过来
2026-04-14	瑜伽垫	trash			没人问，直接扔了
2026-04-15	婴儿车	sold	900		41 天回血
2026-04-20	书架	ask	80		自提
2026-05-01	冲锋衣	list	400	1299	apparel	穿过两次，吊牌还在
2026-05-02	书架	sold	80		53 天回血
2026-05-10	显示器	list	900	1899	electronics	2K 27 寸，当年旗舰
2026-06-01	电饭锅	list	400	899	appliance	IH 电饭煲
2026-06-10	游戏卡	list	120	300	toy	塞尔达两枚
2026-06-20	空气炸锅	list	250	499	appliance	用了三次
2026-06-25	落地灯	list	90	299	furniture	宜家诺米利
2026-07-01	游戏卡	pull			算了，留给外甥
2026-07-05	电饭锅	ask	350		现在能自提吗
2026-07-10	无人机	list	4500	6499	electronics	吃灰三年，忍痛
2026-07-12	电饭锅	price	330		降 20 表个态
2026-07-18	落地灯	ask	60		60 卖不卖
2026-07-30	显示器	ask	700		700 现金现提
2026-08-01	无人机	price	3999		周年庆降 500
"""

LEDGERS = [("events.tsv", EVENTS)]

SNAPSHOTS = [
    ("sample-report.txt", "report", [], 4),
    ("sample-stale.txt", "stale", [], 4),
    ("sample-elastic.txt", "elastic", [], 0),
    ("sample-verdict.txt", "verdict", ["电饭锅"], 4),
    ("sample-verdict-sold.txt", "verdict", ["电纸书"], 0),
    ("sample-simulate.txt", "simulate", [], 0),
    ("sample-categories.txt", "categories", [], 0),
    ("sample-validate.txt", "validate", [], 0),
]


def main():
    checking = "--check" in sys.argv
    for fname, want in LEDGERS:
        if checking:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != want:
                    sys.exit("%s 与构建器不一致：请重新运行 build_examples.py" % fname)
        else:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(want)
            print("wrote %s" % fname)
    for fname, cmd, extra, want_code in SNAPSHOTS:
        run = [sys.executable, CLI, cmd, os.path.join(HERE, "events.tsv"),
               "--as-of", AS_OF] + extra
        done = subprocess.run(run, capture_output=True, text=True)
        if done.returncode != want_code:
            sys.exit("%s: 期望 exit %d，实得 %d\n%s%s"
                     % (fname, want_code, done.returncode, done.stdout, done.stderr))
        if checking:
            with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
                if fh.read() != done.stdout:
                    sys.exit("%s 与重渲染不一致：请重新运行 build_examples.py" % fname)
        else:
            with open(os.path.join(HERE, fname), "w", encoding="utf-8") as fh:
                fh.write(done.stdout)
            print("wrote %s (exit %d)" % (fname, done.returncode))
    print("OK")


if __name__ == "__main__":
    main()
