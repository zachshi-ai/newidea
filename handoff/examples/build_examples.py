#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the handoff example ledger and snapshots.

The demo is 老李 (52 岁) — the family's information hub. A colleague's
heart attack made him sit down and finally write the ledger down. His
12 entries tell the whole anatomy of a handoff book:

  * three STALE lamps — the fund app verified 2021 (password clue on a
    blue notebook), the critical-illness policy verified 2024 (60-day
    grace period), and the old mailbox "kept in his head" since 2022;
  * two SOLO lamps — things only he knows: the fund account and the
    untraceable mailbox (where + clue both empty → NO-TRACE too);
  * one MISSING category — debt. He lent his cousin 50,000 in 2018,
    no IOU, can't bring himself to say it out loud. The report's blind-
    spot question says it for him;
  * two urgent rows — the phone number with family-plan auto-deduction
    and the video membership still billing every year: the first page
    of the brief is always for the things that keep bleeding.

Time machine: --as-of 2024-02-10 rewinds to the day he first checked —
back then only the fund app was stale. Freshness is relative; the
ledger's checked trail (2024 → 2026) is the proof.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "handoff.py")

LEDGER = """\
# handoff 样例账本 · 老李的交底(52 岁,同事心梗住院之后开始盘点)
# 一行一件要紧物:category/title/scale/where/key_clue/knows/verified[/step/urgent/note]
# 盘点轨迹:2024-02-10 第一次下决心,2026-09-06 又盘了一次——位置会挪,密码会改,账本要跟着活
# checked: 2024-02-10
# checked: 2026-09-06
category\ttitle\tscale\twhere\tkey_clue\tknows\tverified\tstep\turgent\tnote
bank\t工行工资卡(尾号6621)\ttw\t客厅五斗柜第二层红色铁盒\t预留手机尾号8801\tspouse\t2026-03-15\t双方身份证+结婚证,任意网点\t\t房贷代扣账户,别动
bank\t微信零钱+零钱通\tk\t微信-我-服务-钱包\t绑定手机尾号8801\tspouse\t2026-09-06\t客服 95017\t\t日常买菜的钱
bank\t支付宝余额+余额宝\tw\t手机App\t登录手机尾号8801\tkids\t2026-08-12\t客服 95188\t\t水电煤代扣从这里走
invest\t基金账户(尾号3307)\tw\t手机App 天天基金\t交易密码在蓝皮笔记本第3页\tself-only\t2021-11-02\t客服 4000888108\t\t换过手机,App 还能登
invest\t公积金(市公积金中心)\ttw\t支付宝-市民中心可查\t身份证号即可查\tfamily\t2026-09-06\t线下市民之家\t\t贷款还清后剩这些
policy\t重疾险(保额50万)\ttw\t书柜第三层太平洋保单夹\t缴费绑定工行卡\tspouse\t2024-02-10\t打 95500 报身份证号\t\t宽限期 60 天,过了失效
deed\t房产证+购房合同\thw\t卧室衣柜顶上绿色文件袋\t和户口本放在一起\tspouse\t2026-09-06\t不动产登记中心可查\t\t婚内共同财产
deed\t户口本+结婚证\tw\t卧室衣柜顶上绿色文件袋\t—\tspouse\t2026-09-06\t—\t\t迁户口要用
digital\t手机号(尾号8801)\tna\t随身\t服务密码=身份证后6位\tfamily\t2026-09-06\t营业厅补卡\ty\t亲情号代扣着话费,停机会连锁
digital\t视频会员年费自动续费\tk\t微信支付-自动扣费\t钱包-支付设置可关\tspouse\t2026-08-20\t微信钱包-支付设置\ty\t人不在也年年扣
digital\t旧邮箱+网盘\tna\t—\t—\tself-only\t2022-05-01\t—\t\t一直想写下来,一直没写
"""

ASOF = "2026-09-06"

SNAPSHOTS = [
    ("sample-report.txt",
     ["report", "handoff.tsv"]),
    ("sample-report-asof-2024.txt",
     ["report", "handoff.tsv", "--as-of", "2024-02-10"]),
    ("sample-brief.txt",
     ["brief", "handoff.tsv", "--top", "5"]),
    ("sample-brief-mask.txt",
     ["brief", "handoff.tsv", "--top", "5", "--mask"]),
    ("sample-who.txt",
     ["who", "handoff.tsv"]),
    ("sample-validate.txt",
     ["validate", "handoff.tsv"]),
]


def build(check: bool) -> int:
    ledger_path = os.path.join(HERE, "handoff.tsv")
    if check:
        with open(ledger_path, "r", encoding="utf-8") as f:
            if f.read() != LEDGER:
                print("MISMATCH: handoff.tsv drifted from build_examples.py",
                      file=sys.stderr)
                return 1
    else:
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(LEDGER)

    ok = True
    for name, argv in SNAPSHOTS:
        path = os.path.join(HERE, name)
        proc = subprocess.run([sys.executable, CLI] + argv,
                              capture_output=True, text=True,
                              encoding="utf-8", cwd=HERE)
        expected = proc.stdout
        if check:
            with open(path, "r", encoding="utf-8") as f:
                actual = f.read()
            if actual != expected:
                print("MISMATCH: %s drifted (rerun build_examples.py)" % name,
                      file=sys.stderr)
                ok = False
            # 快照的退出码也要复现(report/who/brief 因灯亮 exit 4 属设计内)
            print("%-28s exit=%d" % (name, proc.returncode))
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(expected)
            print("%-28s exit=%d" % (name, proc.returncode))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(build(check="--check" in sys.argv[1:]))
