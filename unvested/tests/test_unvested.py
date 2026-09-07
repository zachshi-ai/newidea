#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unvested 验收测试。

样例数字全部先手算再钉(as-of 2026-06-30 = 巨潮 price_date = 账本最大日期):
  星尘(2022-03-01, 48,000 股, 4y/1y cliff quarterly, strike 1.20, 价 8.50@2024-07-15):
    cliff 2023-03-01 = 12,000;此后每季 3,000。2024-06-30 离职时已归属
    12,000 + 5×3,000 = 27,000;未归属 21,000。窗口 = 2024-06-30+90d =
    2024-09-28,没行权 → as-of 2026 全部作废,净代价 27,000×(8.50−1.20)
    = 197,100。价格 715 天前(>548)→ 旧地图。
  巨潮(2023-07-01, rsu 24,000 股, 4y/1y cliff quarterly, 价 32.00@2026-06-30):
    cliff 2024-07-01 = 6,000;此后每季 1,500;到 2026-06-30 已归属
    6,000 + 7×1,500 = 16,500;2025-12-15 回购 2,000 股 @31.00 落袋 62,000;
    在册 = 16,500 − 2,000 = 14,500,纸面 22,000×32 = 704,000。
    ——开发中自纠:青苔月度节点手算 220,程序 208:range 从 cliff+step
    (13)开始而非 15,k=36 → 7,500//36 = 208 余 12。手算错,程序对。
  青苔(2024-09-20, option 10,000 股, strike 0.80, 4y/1y cliff monthly, 无价格):
    cliff 2025-09-20 = 2,500;此后每月 base 208(36 节点,末节点 220)。
    到 2026-06-30 已归属 2,500 + 9×208 = 4,372;2026-03-15 行权 1,000
    (当时已归属 3,820,合法);在册 3,372,行权现金 3,372×0.80 = 2,697.60。
  深流(2025-10-01, option 16,000 股, strike 2.00, 4y/1y cliff quarterly, 价 6.00@2026-04-01):
    cliff 2026-10-01 = 4,000(93 天后,25%)→ CLIFF-AHEAD;已归属 0。
  恒等式:98,000 ≡ 29,128+17,872+1,000+2,000+21,000+27,000(六桶)。
  时间机器 2024-09-10:窗口还剩 18 天(2024-09-28−2024-09-10),27,000 股
  在册纸面 229,500,行权现金 32,400 → WINDOW-CLOSING;巨潮价格在未来
  (2026-06-30)→ 只数股份;青苔/深流是后视行。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
CLI = os.path.join(PKG, "unvested.py")
EX = os.path.join(PKG, "examples")
sys.path.insert(0, PKG)

import unvested as uv  # noqa: E402

GRANT_HEADER = ("company\tkind\tgrant_date\tshares\tstrike\tvest_years\tcliff_months\t"
                "interval\tstatus\tend_date\twindow_days\tlatest_price\tprice_date\tnote\n")
EVENT_HEADER = "date\tcompany\tevent\tshares\tprice\tnote\n"
SCHED_HEADER = "company\tdate\tshares\n"


def grow(company="甲", kind="option", gd="2023-01-01", shares="10000", strike=None,
         vy="4", cm="12", itv="quarterly", status="active", ed="", wd="",
         lp="", pd="", note=""):
    if strike is None:
        strike = "0" if kind == "rsu" else "1.00"
    return "\t".join([company, kind, gd, shares, strike, vy, cm, itv, status,
                      ed, wd, lp, pd, note])


def erow(date_, company, event, shares, price="", note=""):
    return "\t".join([date_, company, event, shares, price, note])


class Base(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def mk(self, grants, events=None, sched=None):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        with open(os.path.join(d, "grants.tsv"), "w", encoding="utf-8") as fh:
            fh.write(GRANT_HEADER + "".join(r + "\n" for r in grants))
        if events is not None:
            with open(os.path.join(d, "events.tsv"), "w", encoding="utf-8") as fh:
                fh.write(EVENT_HEADER + "".join(r + "\n" for r in events))
        if sched is not None:
            with open(os.path.join(d, "schedule.tsv"), "w", encoding="utf-8") as fh:
                fh.write(SCHED_HEADER + "".join(r + "\n" for r in sched))
        return d

    def go(self, argv, d):
        proc = subprocess.run([sys.executable, CLI] + argv + ["--dir", d],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------- 样例字面值

class SampleLedger(Base):
    def test_report_literal_values(self):
        code, out, _ = self.go(["report"], EX)
        self.assertEqual(code, 4)
        self.assertIn("as-of 2026-06-30", out)
        self.assertIn("98,000", out)
        self.assertIn("27,000", out)        # 星尘已归属
        self.assertIn("16,500", out)        # 巨潮已归属
        self.assertIn("4,372", out)         # 青苔已归属(手算 220 错,程序 208 对)
        self.assertIn("¥704,000", out)      # 巨潮在册纸面
        self.assertIn("¥62,000", out)       # 已落袋
        self.assertIn("¥197,100", out)      # 星尘窗口作废净代价
        self.assertIn("¥178,500", out)      # 星尘离职作废纸面
        self.assertIn("¥96,000", out)       # 深流纸面
        self.assertIn("¥39,200", out)       # 行权现金合计 32,000+7,200
        self.assertIn("掏 ¥7,200(strike 0.8)", out)  # 青苔:没有估值,行权现金也确定
        self.assertIn("715 天前的旧地图", out)
        self.assertIn("93 天后", out)        # 深流 cliff
        self.assertIn("不发明估值", out)

    def test_report_blown_lamp_exit4(self):
        code, out, _ = self.go(["report"], EX)
        self.assertEqual(code, 4)
        self.assertIn("🔴 BLOWN-WINDOW", out)
        self.assertIn("2024-09-28 已关", out)
        self.assertIn("这笔损失无人替你记账", out)
        self.assertNotIn("WINDOW-CLOSING", out)

    def test_report_cliff_ahead_lamp(self):
        code, out, _ = self.go(["report"], EX)
        self.assertIn("🟡 CLIFF-AHEAD", out)
        self.assertIn("深流科技", out)
        self.assertIn("25.0%", out)

    def test_time_machine_window_closing(self):
        code, out, _ = self.go(["report", "--as-of", "2024-09-10"], EX)
        self.assertEqual(code, 4)
        self.assertIn("as-of 2024-09-10 (时间机器", out)
        self.assertIn("🔴 WINDOW-CLOSING", out)
        self.assertIn("只剩 18 天", out)
        self.assertIn("¥32,400", out)        # 27,000×1.20
        self.assertIn("¥229,500", out)       # 27,000×8.50 在册
        self.assertIn(" future(后视行)", out)  # 青苔/深流还没授予
        self.assertIn("无价格,只数股份", out)  # 巨潮价格在未来,被排除
        self.assertNotIn("BLOWN-WINDOW", out)

    def test_time_machine_blown_unhappens(self):
        # 窗口关闭前一刻:作废尚未发生——灯会变,数字会回来
        code, out, _ = self.go(["report", "--as-of", "2024-09-28"], EX)
        self.assertEqual(code, 4)
        self.assertNotIn("BLOWN", out)
        # 恰在窗口最后一天:window_left = 0 < 30 → WINDOW-CLOSING 亮
        self.assertIn("WINDOW-CLOSING", out)
        code, out, _ = self.go(["report", "--as-of", "2024-09-29"], EX)
        self.assertEqual(code, 4)
        self.assertIn("BLOWN-WINDOW", out)   # 过一天,归零

    def test_exit_today_literal(self):
        code, out, _ = self.go(["exit"], EX)
        self.assertEqual(code, 0)
        self.assertIn("假设 2026-06-30 离职", out)
        self.assertIn("已于 2024-06-30 离职——命运已入账", out)
        self.assertIn("已归属 16,500 股(68.8%)", out)
        self.assertIn("未归属 7,500 股作废", out)
        self.assertIn("可带走纸面 ¥528,000", out)   # 16,500×32
        self.assertIn("作废纸面代价 ¥240,000", out)  # 7,500×32
        self.assertIn("需掏 ¥2,697.60", out)
        self.assertIn("下一节点 2026-07-01(明天)", out)
        self.assertIn("推演是事实不是建议", out)

    def test_exit_year_end_literal(self):
        code, out, _ = self.go(["exit", "--date", "2026-12-31"], EX)
        self.assertEqual(code, 0)
        # 巨潮:12-31 前多两季,带走 19,500
        self.assertIn("已归属 19,500 股(81.2%)", out)
        self.assertIn("未归属 4,500 股作废", out)
        self.assertIn("¥624,000", out)       # 19,500×32
        # 青苔:月度节点,带走 2,500+15×208 = 5,620,窗口至 2027-03-31
        self.assertIn("已归属 5,620 股", out)
        self.assertIn("需掏 ¥3,696", out)    # (5,620−1,000)×0.80
        # 深流:cliff 2026-10-01 在 12-31 之前——撑过悬崖带走 4,000
        self.assertIn("已归属 4,000 股(25.0%)", out)
        self.assertIn("未归属 12,000 股作废", out)
        self.assertIn("下一节点 2027-01-01", out)

    def test_clock_literal(self):
        code, out, _ = self.go(["clock"], EX)
        self.assertEqual(code, 0)
        self.assertIn("== 倒计时(升序)==", out)
        self.assertIn("2026-07-01  巨潮科技", out)
        self.assertIn("CLIFF +4,000 股(25.0%)", out)
        self.assertIn("全部归属完成", out)
        self.assertIn("期权 10 年大限", out)
        self.assertIn("== 未来 12 个月归属日历(至 2027-06-30)==", out)
        self.assertIn("(CLIFF)", out)
        self.assertIn("日历只摆事实", out)
        # 巨潮最后一个节点是 2027-07-01,恰在展望窗外
        code, out, _ = self.go(["clock", "--months", "13"], EX)
        self.assertIn("2027-07-01  巨潮科技      +1,500 股", out)

    def test_validate_literal_identity(self):
        code, out, _ = self.go(["validate"], EX)
        self.assertEqual(code, 0)
        self.assertIn("星尘科技", out)
        self.assertIn("48,000 ≡ 0+0+0+0+21,000+27,000", out)
        self.assertIn("24,000 ≡ 7,500+14,500+0+2,000+0+0", out)
        self.assertIn("10,000 ≡ 5,628+3,372+1,000+0+0+0", out)
        self.assertIn("16,000 ≡ 16,000+0+0+0+0+0", out)
        self.assertIn("98,000 ≡ 29,128+17,872+1,000+2,000+21,000+27,000", out)
        self.assertIn("残差 +0.00e+00", out)
        self.assertIn("账本健康。", out)
        self.assertIn("(2 家公司)", out)     # 事件重放覆盖巨潮/青苔
        self.assertIn("(0 行覆盖)", out)     # 样例无 schedule

    def test_zero_wall_clock_double_run_identical(self):
        outs = []
        for _ in range(2):
            code, out, _ = self.go(["report"], EX)
            outs.append(out)
        self.assertEqual(outs[0], outs[1])
        src = open(CLI, encoding="utf-8").read()
        self.assertNotIn("datetime.now", src)
        self.assertNotIn("date.today", src)
        self.assertNotIn("time.time", src)

    def test_report_prints_basename_only(self):
        code, out, _ = self.go(["report"], EX)
        self.assertIn("(examples)", out)
        self.assertNotIn(EX, out)


# ---------------------------------------------------------------- 归属算术

class VestingMath(Base):
    GR = grow("甲", gd="2024-01-01", shares="1200")

    def test_cliff_boundary_inclusive(self):
        led = uv.Ledger(self.mk([self.GR]))
        g = led.grants[0]
        # cliff 2025-01-01:前一天 0,当天 300(悬崖日含当天)
        self.assertEqual(led.vested_on(g, date(2024, 12, 31)), 0)
        self.assertEqual(led.vested_on(g, date(2025, 1, 1)), 300)

    def test_quarterly_steps(self):
        # cliff 300 之后,900 股摊 12 个季度 = 每季 75
        led = uv.Ledger(self.mk([self.GR]))
        g = led.grants[0]
        self.assertEqual(led.vested_on(g, date(2025, 4, 1)), 375)   # 300+1×75
        self.assertEqual(led.vested_on(g, date(2025, 6, 30)), 375)
        self.assertEqual(led.vested_on(g, date(2025, 7, 1)), 450)   # +2×75
        self.assertEqual(led.vested_on(g, date(2028, 1, 1)), 1200)

    def test_one_shot_cliff(self):
        # cliff == 全程:一次性归属
        led = uv.Ledger(self.mk([grow("甲", gd="2024-01-01", shares="1000", vy="2", cm="24")]))
        g = led.grants[0]
        nodes = led.nodes_of(g)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(led.vested_on(g, date(2025, 12, 31)), 0)
        self.assertEqual(led.vested_on(g, date(2026, 1, 1)), 1000)

    def test_zero_cliff_annual(self):
        # 无悬崖,年付:5 个节点(含授予日)平摊,每节点 20%
        led = uv.Ledger(self.mk([grow("甲", gd="2024-01-01", shares="1000", cm="0", itv="annual")]))
        g = led.grants[0]
        self.assertEqual(led.vested_on(g, date(2024, 1, 1)), 200)
        self.assertEqual(led.vested_on(g, date(2024, 12, 31)), 200)
        self.assertEqual(led.vested_on(g, date(2025, 1, 1)), 400)
        self.assertEqual(led.vested_on(g, date(2028, 1, 1)), 1000)

    def test_month_end_clamping(self):
        # 01-31 起步,月节点月末钳制:2 月没有 31 日
        led = uv.Ledger(self.mk([grow("甲", gd="2023-01-31", shares="1200", cm="0", itv="monthly")]))
        g = led.grants[0]
        nodes = led.nodes_of(g)
        d0 = nodes[0][0]
        self.assertEqual((d0.month, d0.day), (1, 31))
        d1 = nodes[1][0]
        self.assertEqual((d1.month, d1.day), (2, 28))
        # 闰年吃得上 29
        led2 = uv.Ledger(self.mk([grow("乙", gd="2024-01-31", shares="1200", cm="0", itv="monthly")]))
        d1b = led2.nodes_of(led2.grants[0])[1][0]
        self.assertEqual((d1b.month, d1b.day), (2, 29))

    def test_remainder_goes_to_last_node(self):
        # 10,001 股:cliff 2,500 + 12 节点,base 625 余 1 → 末节点 626
        led = uv.Ledger(self.mk([grow("甲", gd="2023-01-01", shares="10001")]))
        g = led.grants[0]
        nodes = led.nodes_of(g)
        self.assertEqual(nodes[0][1], 2500)
        self.assertEqual(sum(n for _, n, _, _ in nodes), 10001)
        self.assertEqual(nodes[-1][1], 626)
        self.assertEqual(nodes[-2][1], 625)
        self.assertTrue(nodes[-1][3])       # 末节点标记 final

    def test_end_date_caps_vesting(self):
        led = uv.Ledger(self.mk([grow("甲", gd="2023-01-01", shares="1200",
                                      status="left", ed="2024-06-30")]))
        g = led.grants[0]
        # 日程表上有 2025-01-01 的节点,但离职后不再归属:
        # 到离职日已归属 = cliff 300(2024-01-01)+ 75(2024-04-01)= 375
        self.assertEqual(led.vested_on(g, date(2024, 6, 30)), 375)
        self.assertEqual(led.vested_on(g, date(2025, 1, 1)), 375)

    def test_dual_path_parity_grid(self):
        # 前向累加 == 补集 == 判定式:样例 + 余数构造,37 天步进全网格
        led = uv.Ledger(EX)
        led2 = uv.Ledger(self.mk([grow("甲", gd="2023-01-01", shares="10001"),
                                  grow("乙", "rsu", gd="2023-03-15", shares="7777", cm="6"),
                                  grow("丙", gd="2023-06-01", shares="500", cm="0", itv="annual")]))
        for L in (led, led2):
            for g in L.grants:
                d = g.grant_date
                end = g.grant_date + timedelta(days=5 * 366)
                while d <= end:
                    a = L.vested_forward(g, d)
                    b = L.vested_complement(g, d)
                    c = L.vested_on(g, d)
                    self.assertEqual(a, b, "%s %s" % (g.company, d))
                    self.assertEqual(b, c, "%s %s" % (g.company, d))
                    d += timedelta(days=37)

    def test_schedule_override(self):
        # performance vest:日程表整表覆盖公式,授予协议永远赢
        d = self.mk(
            [grow("甲", gd="2024-01-01", shares="1000")],
            sched=["甲\t2025-01-01\t500", "甲\t2026-01-01\t300", "甲\t2027-06-30\t200"])
        led = uv.Ledger(d)
        g = led.grants[0]
        self.assertEqual(led.vested_on(g, date(2025, 6, 1)), 500)
        self.assertEqual(led.vested_on(g, date(2026, 6, 30)), 800)
        code, out, _ = self.go(["validate"], d)
        self.assertEqual(code, 0)
        self.assertIn("(3 行覆盖)", out)

    def test_schedule_sum_mismatch_exit2(self):
        d = self.mk([grow("甲", gd="2024-01-01", shares="1000")],
                    sched=["甲\t2025-01-01\t500", "甲\t2026-01-01\t300"])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("Σshares=800 ≠ 授予股数 1,000", err)

    def test_schedule_unknown_company_exit2(self):
        d = self.mk([grow("甲")], sched=["乙\t2025-01-01\t100"])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("悬空引用", err)

    def test_schedule_multi_grant_exit2(self):
        d = self.mk([grow("甲", gd="2023-01-01", shares="500"),
                     grow("甲", gd="2024-01-01", shares="500")],
                    sched=["甲\t2025-01-01\t1000"])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("整表覆盖", err)


# ---------------------------------------------------------------- 事件与状态

class EventsAndStates(Base):
    def test_exercise_legality_and_buckets(self):
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200")],
                    [erow("2024-02-01", "甲", "exercise", "300")])
        led = uv.Ledger(d)
        st = led.state(date(2024, 6, 1), 10)["甲"]
        # 2024-06-01 已归属 = cliff 300 + 75(2024-04-01)= 375
        self.assertEqual(st["UNVESTED"], 825)
        self.assertEqual(st["AVAILABLE"], 75)    # 375 已归属 − 300 已行权
        self.assertEqual(st["EXERCISED"], 300)
        code, out, _ = self.go(["validate"], d)
        self.assertEqual(code, 0)
        # validate 的 as-of 缺省锚到账本最大日期=事件日 2024-02-01:彼时
        # 已归属 = cliff 300,恒等式 1,200 ≡ 900+0+300
        self.assertIn("1,200 ≡ 900+0+300+0+0+0", out)

    def test_exercise_over_vested_exit2(self):
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200")],
                    [erow("2023-06-01", "甲", "exercise", "300")])  # cliff 未到
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("不能行权还没归属的股份", err)

    def test_exercise_on_rsu_exit2(self):
        d = self.mk([grow("甲", "rsu", gd="2023-01-01", shares="1200")],
                    [erow("2024-06-01", "甲", "exercise", "300")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("没有行权这件事", err)

    def test_exercise_after_window_exit2(self):
        d = self.mk([grow("甲", gd="2022-01-01", shares="1200",
                          status="left", ed="2023-01-01")],
                    [erow("2023-04-03", "甲", "exercise", "300")])  # 窗口 2023-04-01 关
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("窗口关了,账本拒载", err)

    def test_exercise_within_window_ok(self):
        d = self.mk([grow("甲", gd="2022-01-01", shares="1200",
                          status="left", ed="2023-01-01")],
                    [erow("2023-03-15", "甲", "exercise", "300")])
        code, out, _ = self.go(["validate"], d)
        self.assertEqual(code, 0)

    def test_exercise_before_grant_exit2(self):
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200")],
                    [erow("2022-12-01", "甲", "exercise", "300")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("早于最早授予日", err)

    def test_unknown_company_event_exit2(self):
        d = self.mk([grow("甲")], [erow("2024-06-01", "乙", "tender", "100", "2.0")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("悬空引用", err)

    def test_tender_without_price_exit2(self):
        d = self.mk([grow("甲", "rsu", gd="2023-01-01", shares="1200")],
                    [erow("2024-06-01", "甲", "tender", "100")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("落袋账没有价格就不是账", err)

    def test_tender_over_pool_exit2(self):
        d = self.mk([grow("甲", "rsu", gd="2023-01-01", shares="1200")],
                    [erow("2023-06-01", "甲", "tender", "100", "2.0")])  # cliff 未到
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("超过当日已归属", err)

    def test_option_tender_needs_exercise_first(self):
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200")],
                    [erow("2024-06-01", "甲", "tender", "100", "2.0")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("卖出不存在的股份", err)

    def test_exercise_price_forbidden(self):
        # 行权价是授予条款不是事件属性——填了 price 直接拒载
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200")],
                    [erow("2024-06-01", "甲", "exercise", "100", "2.0")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("不是事件属性", err)

    def test_window_blown_computed_not_entered(self):
        # 作废不用你填——离职+窗口关闭后自动归零,身份恒等式照平
        d = self.mk([grow("甲", gd="2022-01-01", shares="1200",
                          status="left", ed="2023-01-01", lp="10", pd="2024-06-01")])
        led = uv.Ledger(d)
        st = led.state(date(2024, 6, 1), 10)["甲"]
        self.assertEqual(st["F_WIN"], 300)      # cliff 300 在窗口内没行权
        self.assertEqual(st["F_UNVEST"], 900)
        self.assertEqual(st["AVAILABLE"], 0)
        code, out, _ = self.go(["validate"], d)
        self.assertEqual(code, 0)
        self.assertIn("1,200 ≡ 0+0+0+0+900+300", out)

    def test_topup_fifo_allocation(self):
        # 同公司两份授予:行权 4,000 超过公司池 3,750 → 拒绝(不静默吞超额)
        d = self.mk([grow("甲", gd="2022-01-01", shares="12000",
                          status="left", ed="2023-04-15"),
                     grow("甲", gd="2023-01-01", shares="12000",
                          status="left", ed="2023-04-15")],
                    [erow("2023-05-01", "甲", "exercise", "4000")])
        # g1 到 2023-04-15 已归属:cliff 3,000(2023-01-01)+ 750(2023-04-01)= 3,750
        led = uv.Ledger(d)
        g1, g2 = led.grants
        self.assertEqual(led.vested_on(g1, date(2023, 4, 15)), 3750)
        self.assertEqual(led.vested_on(g2, date(2023, 4, 15)), 0)
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("不能行权还没归属的股份", err)

    def test_topup_fifo_legal_split(self):
        # 行权 3,750:恰好吃光 g1 的池,合法;g2 未归属整体作废
        d = self.mk([grow("甲", gd="2022-01-01", shares="12000",
                          status="left", ed="2023-04-15"),
                     grow("甲", gd="2023-01-01", shares="12000",
                          status="left", ed="2023-04-15")],
                    [erow("2023-05-01", "甲", "exercise", "3750")])
        led = uv.Ledger(d)
        st = led.state(date(2023, 6, 1), 10)["甲"]
        self.assertEqual(st["EXERCISED"], 3750)
        self.assertEqual(st["AVAILABLE"], 0)
        self.assertEqual(st["F_UNVEST"], 20250)   # (12000−3750) + 12000
        code, out, _ = self.go(["validate"], d)
        self.assertEqual(code, 0)
        self.assertIn("24,000 ≡ 0+0+3,750+0+20,250+0", out)

    def test_term_expired_lamp(self):
        # 授予 12 年前,4 年 vest 完早就没行权——10 年大限一过全部作废
        d = self.mk([grow("甲", gd="2016-01-01", shares="1000", lp="5", pd="2026-06-30")])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 4)
        self.assertIn("🔴 TERM-EXPIRED", out)
        self.assertIn("2026-01-01 已过", out)

    def test_dead_company_zero_value(self):
        d = self.mk([grow("甲", gd="2022-01-01", shares="1000",
                          status="dead", ed="2024-01-01", lp="8", pd="2023-06-01")])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 0)                 # dead 是黄灯不是红灯
        self.assertIn("🟡 DEAD-STAKE", out)
        self.assertIn("全部价值按 0 计", out)
        self.assertNotIn("¥8,000", out)           # 不按 8 元幻估值挂账


# ---------------------------------------------------------------- 灯与阈值

class LampsAndThresholds(Base):
    def make_left(self, left_date, pd="2026-06-30", warn=30):
        # 12,000 股 4y/1y cliff quarterly,cliff 2023-06-01 已过 → 在册 11,250
        return self.mk([grow("甲", gd="2022-06-01", shares="12000", strike="1.00",
                             status="left", ed=left_date, lp="10", pd=pd)])

    def test_window_closing_exact_line_off(self):
        # left = as-of − 60d → wend − as-of 恰 30 天:恰线不亮
        left = (date(2026, 6, 30) - timedelta(days=60)).strftime("%Y-%m-%d")
        code, out, _ = self.go(["report"], self.make_left(left))
        self.assertEqual(code, 0)
        self.assertNotIn("WINDOW-CLOSING", out)

    def test_window_closing_one_day_under_fires(self):
        left = (date(2026, 6, 30) - timedelta(days=61)).strftime("%Y-%m-%d")
        code, out, _ = self.go(["report"], self.make_left(left))
        self.assertEqual(code, 4)
        self.assertIn("🔴 WINDOW-CLOSING", out)
        self.assertIn("只剩 29 天", out)
        self.assertIn("11,250 股未行权", out)
        self.assertIn("¥11,250", out)             # 11,250×1.00 行权现金

    def test_warn_days_override(self):
        left = (date(2026, 6, 30) - timedelta(days=60)).strftime("%Y-%m-%d")
        code, out, _ = self.go(["report", "--warn-days", "31"],
                               self.make_left(left))
        self.assertEqual(code, 4)
        self.assertIn("WINDOW-CLOSING", out)

    def test_stale_price_exact_line_off(self):
        # pd = as-of − 548 → 不亮;− 549 → 亮。
        # 需要一个更晚的锚点日期把 as-of 钉在 2026-06-30(否则 as-of 锚到 pd 本身)
        pd_off = (date(2026, 6, 30) - timedelta(days=548)).strftime("%Y-%m-%d")
        d = self.mk([grow("甲", gd="2023-01-01", shares="1200", lp="3", pd=pd_off),
                     grow("乙", "rsu", gd="2023-01-01", shares="500",
                          lp="9", pd="2026-06-30")])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 0)
        self.assertNotIn("STALE-PRICE", out)
        pd_on = (date(2026, 6, 30) - timedelta(days=549)).strftime("%Y-%m-%d")
        d2 = self.mk([grow("甲", gd="2023-01-01", shares="1200", lp="3", pd=pd_on),
                      grow("乙", "rsu", gd="2023-01-01", shares="500",
                           lp="9", pd="2026-06-30")])
        code, out, _ = self.go(["report"], d2)
        self.assertIn("🟡 STALE-PRICE", out)
        self.assertIn("549 天前的旧地图", out)

    def test_cliff_ahead_thresholds(self):
        # cliff 在 180 天窗内且 ≥10% → 亮;>180 天或 <10% → 不亮
        g_on = grow("甲", gd="2025-07-20", shares="10000", lp="5",
                    pd="2026-06-30")   # cliff 2026-07-20 = 20 天,25%
        code, out, _ = self.go(["report"], self.mk([g_on]))
        self.assertIn("🟡 CLIFF-AHEAD", out)
        g_far = grow("甲", gd="2026-01-05", shares="10000", lp="5",
                     pd="2026-06-30")  # cliff 2027-01-05 = 189 天
        code, out, _ = self.go(["report"], self.mk([g_far]))
        self.assertNotIn("CLIFF-AHEAD", out)
        g_small = grow("甲", gd="2026-05-15", shares="10000", cm="2", lp="5",
                       pd="2026-06-30")  # cliff 2026-07-15 = 15 天,但 416 股 4.2%
        code, out, _ = self.go(["report"], self.mk([g_small]))
        self.assertNotIn("CLIFF-AHEAD", out)

    def test_cliff_days_override(self):
        g_far = grow("甲", gd="2026-01-05", shares="10000", lp="5", pd="2026-06-30")
        code, out, _ = self.go(["report", "--cliff-days", "200"], self.mk([g_far]))
        self.assertIn("CLIFF-AHEAD", out)


# ---------------------------------------------------------------- 账坏网格

class BadLedgerGrid(Base):
    def bad(self, row, msg, events=None):
        d = self.mk([row], events)
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2, err)
        self.assertIn(msg, err)

    def test_unknow_kind(self):
        self.bad(grow("甲", kind="stock"), "未知 kind")

    def test_unknown_status(self):
        self.bad(grow("甲", status="gone"), "未知 status")

    def test_unknown_interval(self):
        self.bad(grow("甲", itv="weekly"), "未知 interval")

    def test_zero_shares(self):
        self.bad(grow("甲", shares="0"), "正整数")

    def test_negative_shares(self):
        self.bad(grow("甲", shares="-5"), "正整数")

    def test_option_missing_strike(self):
        self.bad(grow("甲", strike=""), "不能不填")

    def test_negative_strike(self):
        self.bad(grow("甲", strike="-1"), "不能为负")

    def test_rsu_with_strike(self):
        self.bad(grow("甲", "rsu", strike="5"), "没有行权价")

    def test_rsu_with_window(self):
        self.bad(grow("甲", "rsu", wd="90"), "没有行权窗口")

    def test_left_without_end_date(self):
        self.bad(grow("甲", status="left"), "不能不填")

    def test_dead_without_end_date(self):
        self.bad(grow("甲", status="dead"), "不能不填")

    def test_end_before_grant(self):
        self.bad(grow("甲", status="left", gd="2023-06-01", ed="2023-05-31"),
                 "早于 grant_date")

    def test_active_with_end_date(self):
        self.bad(grow("甲", status="active", ed="2024-01-01"), "应留空")

    def test_cliff_over_total(self):
        self.bad(grow("甲", vy="4", cm="60"), "必须在 0..48")

    def test_zero_vest_years(self):
        self.bad(grow("甲", vy="0"), "必须为正")

    def test_price_without_date(self):
        self.bad(grow("甲", lp="5"), "同填同空")

    def test_date_without_price(self):
        self.bad(grow("甲", pd="2024-01-01"), "同填同空")

    def test_negative_price(self):
        self.bad(grow("甲", lp="-5", pd="2024-01-01"), "必须为正")

    def test_unpadded_date(self):
        self.bad(grow("甲", gd="2023-6-1"), "补零")

    def test_impossible_calendar_day(self):
        self.bad(grow("甲", gd="2023-02-30"), "不是存在的日历日")

    def test_bad_header(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        with open(os.path.join(d, "grants.tsv"), "w", encoding="utf-8") as fh:
            fh.write("company\tkind\tgrant_date\n甲\toption\t2023-01-01\n")
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("表头必须是", err)

    def test_extra_columns(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        with open(os.path.join(d, "grants.tsv"), "w", encoding="utf-8") as fh:
            fh.write(GRANT_HEADER + grow("甲") + "\textra\n")
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("列数超出表头", err)

    def test_mixed_kind_same_company(self):
        d = self.mk([grow("甲", "option", gd="2023-01-01", shares="500"),
                     grow("甲", "rsu", gd="2024-01-01", shares="500")])
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 2)
        self.assertIn("不混账", err)


# ---------------------------------------------------------------- 空账与出口码

class EmptyAndExitCodes(Base):
    def test_missing_file_exit3(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 3)
        self.assertIn("grants.tsv 不存在", err)
        self.assertIn("第一行抄这里", err)

    def test_empty_file_exit3(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        open(os.path.join(d, "grants.tsv"), "w").close()
        code, _, err = self.go(["report"], d)
        self.assertEqual(code, 3)
        self.assertIn("没有一行授予", err)

    def test_comments_only_exit3(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        with open(os.path.join(d, "grants.tsv"), "w", encoding="utf-8") as fh:
            fh.write("# 只有一行注释\n\n")
        code, _, err = self.go(["clock"], d)
        self.assertEqual(code, 3)

    def test_header_only_exit3(self):
        d = tempfile.mkdtemp()
        self.dirs.append(d)
        with open(os.path.join(d, "grants.tsv"), "w", encoding="utf-8") as fh:
            fh.write(GRANT_HEADER)
        code, _, err = self.go(["validate"], d)
        self.assertEqual(code, 3)

    def test_clean_ledger_report_exit0(self):
        # 一份健康的在职 rsu:无任何红灯
        d = self.mk([grow("甲", "rsu", gd="2023-01-01", shares="1200",
                          lp="3", pd="2026-06-30")])
        code, out, _ = self.go(["report"], d)
        self.assertEqual(code, 0)
        self.assertIn("在册纸面 ¥3,600", out)
        self.assertNotIn("🔴", out)

    def test_command_exit_code_semantics(self):
        self.assertEqual(self.go(["report"], EX)[0], 4)      # 红灯
        self.assertEqual(self.go(["exit"], EX)[0], 0)        # 推演恒 0
        self.assertEqual(self.go(["clock"], EX)[0], 0)       # 日历恒 0
        self.assertEqual(self.go(["validate"], EX)[0], 0)    # 健康


# ---------------------------------------------------------------- as-of 与格式

class AsOfAndFormat(Base):
    def test_asof_default_is_max_date(self):
        led = uv.Ledger(EX)
        self.assertEqual(led.max_date(), date(2026, 6, 30))

    def test_asof_before_everything(self):
        d = self.mk([grow("甲", gd="2026-01-01", shares="1200")])
        code, out, _ = self.go(["report", "--as-of", "2025-06-30"], d)
        self.assertEqual(code, 0)
        self.assertIn("future(后视行)", out)
        self.assertIn("授予尚未开始", out)

    def test_future_event_excluded(self):
        # 回放 2025-06-30:巨潮的回购(2025-12-15)还没发生——没有落袋行
        code, out, _ = self.go(["report", "--as-of", "2025-06-30"], EX)
        self.assertEqual(code, 4)
        self.assertIn("已落袋 ¥0", out)
        self.assertNotIn("唯一离开纸面的钱", out)
        self.assertIn("巨潮科技", out)

    def test_fmt_money_and_shares(self):
        self.assertEqual(uv.fmt_money(197100), "¥197,100")
        self.assertEqual(uv.fmt_money(2697.6), "¥2,697.60")
        self.assertEqual(uv.fmt_money(0), "¥0")
        self.assertEqual(uv.fmt_shares(48000), "48,000")
        self.assertEqual(uv.fmt_shares(0), "0")
        self.assertEqual(uv.fmt_pct(0.6875), "68.8%")
        self.assertEqual(uv.fmt_after(0), "就是今天")
        self.assertEqual(uv.fmt_after(1), "明天")
        self.assertEqual(uv.fmt_after(93), "93 天后")

    def test_add_months_clamp(self):
        self.assertEqual(uv.add_months(date(2023, 1, 31), 1), date(2023, 2, 28))
        self.assertEqual(uv.add_months(date(2024, 1, 31), 1), date(2024, 2, 29))
        self.assertEqual(uv.add_months(date(2023, 1, 31), 13), date(2024, 2, 29))
        self.assertEqual(uv.add_months(date(2024, 3, 31), -1), date(2024, 2, 29))

    def test_tender_shows_bag_line(self):
        code, out, _ = self.go(["report"], EX)
        self.assertIn("已落袋 ¥62,000(1 笔变现,2,000 股)", out)
        self.assertIn("唯一离开纸面的钱", out)


if __name__ == "__main__":
    unittest.main()
