#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""躺亏 · Dormant Loss 验收测试。

覆盖: 到期日几何(对月对日/月末钳制/闰日/不链式)、利率时间线语义(沉默=活期/
转存段/取走结案/提前支取)、躺亏算术(锚=原合同、天基、双算法)、状态桶、
四灯恰线不亮、翻案参数全链、时间机器、账坏类、薄账、零墙钟字节复现、
仓库快照逐字节。
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dormant_loss  # noqa: E402
from dormant_loss import add_months, add_months_walk  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")
CLI = os.path.join(ROOT, "dormant_loss.py")

DEP_HEADER = "bank\tprincipal\trate\tmonths\tstart\ttag\trealized\tnote"
REN_HEADER = "date\ttag\tkind\trate\tterm\tnote"


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = dormant_loss.main(argv)
    return rc, out.getvalue(), err.getvalue()


def dep(bank, principal, rate, months, start, tag="", realized="", note=""):
    return "\t".join([bank, principal, rate, months, start, tag, realized, note])


@contextlib.contextmanager
def ledger_dir(deps, rens=None):
    """临时账本目录;rens 为 renewals.tsv 全部行(含表头)或 None。"""
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "deposits.tsv"), "w", encoding="utf-8") as f:
            f.write(DEP_HEADER + "\n" + "\n".join(deps) + "\n")
        if rens is not None:
            with open(os.path.join(d, "renewals.tsv"), "w", encoding="utf-8") as f:
                f.write("\n".join(rens) + "\n")
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def empty_dir():
    d = tempfile.mkdtemp()
    return d


class TestGeom(unittest.TestCase):
    """到期日几何: 对月对日 + 月末钳制,从原始 day 重算不链式累积。"""

    def test_add_months_basic(self):
        self.assertEqual(add_months(date(2021, 5, 10), 36), date(2024, 5, 10))

    def test_month_end_clamp_from_leap_day(self):
        # 闰日存入 60 月 → 2025 平年钳到 2-28
        self.assertEqual(add_months(date(2020, 2, 29), 60), date(2025, 2, 28))

    def test_leap_day_kept_on_leap_target(self):
        self.assertEqual(add_months(date(2020, 2, 29), 96), date(2028, 2, 29))

    def test_no_chained_clamp(self):
        # 1-31 +1 月 = 2-28,但 +2 月必须回到 3-31(不是 2-28+1 月 = 3-28)
        d = date(2023, 1, 31)
        self.assertEqual(add_months(d, 1), date(2023, 2, 28))
        self.assertEqual(add_months(d, 2), date(2023, 3, 31))
        self.assertEqual(add_months(d, 3), date(2023, 4, 30))

    def test_walk_parity_grid(self):
        # 闭式 == 逐月前向游走: 4 个生辰角 × 0..30 月全网格
        starts = [date(2023, 1, 31), date(2020, 2, 29), date(2023, 5, 10),
                  date(2024, 8, 31)]
        for s in starts:
            for n in range(31):
                self.assertEqual(add_months(s, n), add_months_walk(s, n),
                                 f"{s} +{n}月")


class TestLedgerErrors(unittest.TestCase):
    """账坏类——宁可拒绝,不替你编账(全部 exit 2)。"""

    def assert_bad(self, deps, rens=None, cmd="report"):
        with ledger_dir(deps, rens) as d:
            rc, _, err = run_cli([cmd, "--dir", d])
            self.assertEqual(rc, 2, err)
            self.assertTrue(err.strip())

    def test_missing_column(self):
        d = empty_dir()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        with open(os.path.join(d, "deposits.tsv"), "w", encoding="utf-8") as f:
            f.write("bank\tprincipal\trate\n工行\t100\t3\n")
        rc, _, _ = run_cli(["report", "--dir", d])
        self.assertEqual(rc, 2)

    def test_bad_date(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-13-01")])

    def test_zero_principal(self):
        self.assert_bad([dep("工行", "0", "3", "12", "2023-01-01")])

    def test_negative_rate(self):
        self.assert_bad([dep("工行", "100000", "-1", "12", "2023-01-01")])

    def test_float_months(self):
        self.assert_bad([dep("工行", "100000", "3", "12.5", "2023-01-01")])

    def test_dup_tag(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01"),
                         dep("工行", "200000", "2", "12", "2023-02-01")])

    def test_dangling_renewal_tag(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01")],
                        [REN_HEADER, "2024-01-01\t建行一\trenew\t1.5\t12\t"])

    def test_bad_kind(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01")],
                        [REN_HEADER, "2024-01-01\t工行\t取走\t\t\t"])

    def test_renew_missing_term(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01")],
                        [REN_HEADER, "2024-01-01\t工行\trenew\t1.5\t\t"])

    def test_withdraw_with_rate(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01")],
                        [REN_HEADER, "2024-01-10\t工行\twithdraw\t0.5\t\t"])

    def test_same_day_two_events(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-01")],
                        [REN_HEADER,
                         "2024-01-01\t工行\trenew\t1.5\t12\t",
                         "2024-01-01\t工行\twithdraw\t\t\t"])

    def test_renew_during_term(self):
        # 存续期内不能转存——急用钱是提前支取
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-10")],
                        [REN_HEADER, "2023-06-01\t工行\trenew\t1.5\t12\t"])

    def test_event_before_start(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-10")],
                        [REN_HEADER, "2022-12-01\t工行\twithdraw\t\t\t"])

    def test_event_after_withdraw(self):
        self.assert_bad([dep("工行", "100000", "3", "12", "2023-01-10")],
                        [REN_HEADER,
                         "2024-01-10\t工行\twithdraw\t\t\t",
                         "2024-02-01\t工行\trenew\t1.5\t12\t"])


class TestTimelineSemantics(unittest.TestCase):
    """利率时间线: 沉默就是活期;转存段/取走结案/提前支取/未来行排除。"""

    def test_silence_is_demand(self):
        # 无 renewals: 到期后全程沉默=活期
        with ledger_dir([dep("测试行", "100000", "3.0", "12", "2023-01-10")]) as d:
            rc, out, _ = run_cli(["timeline", "--dir", d,
                                  "--as-of", "2024-07-10", "--demand-rate", "0.05"])
            self.assertEqual(rc, 0)
            self.assertIn("沉默=活期", out)
            self.assertIn("躺亏", out)

    def test_renew_segment_value(self):
        with ledger_dir([dep("测试行", "100000", "2.6", "12", "2022-11-20", tag="甲")],
                        [REN_HEADER, "2023-11-20\t甲\trenew\t1.35\t12\t"]) as d:
            rc, out, _ = run_cli(["timeline", "--dir", d, "--as-of", "2024-11-21"])
            self.assertIn("转存12月", out)
            # 转存段躺亏 = 100000×1.25%×366/365 = 1253.42
            self.assertIn("¥1,253.42", out)

    def test_withdraw_after_maturity_stops_loss(self):
        with ledger_dir([dep("测试行", "100000", "3.0", "12", "2023-01-10")],
                        [REN_HEADER, "2024-01-15\t测试行\twithdraw\t\t\t"]) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertEqual(rc, 0)
            self.assertIn("已取走", out)
            # 活期 5 天躺亏 = 100000×2.95%×5/365 = 40.41
            self.assertIn("¥40.41", out)

    def test_early_withdraw_full_demand(self):
        with ledger_dir([dep("测试行", "100000", "3.0", "12", "2023-01-10")],
                        [REN_HEADER, "2023-06-01\t测试行\twithdraw\t\t\t"]) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertEqual(rc, 0)
            self.assertIn("提前支取", out)
            self.assertIn("提前 223 天", out)
            # 全程 142 天按活期: 躺亏 = 100000×2.95%×142/365 = 1147.67
            self.assertIn("¥1,147.67", out)
            self.assertIn("EARLY-TAX", out)

    def test_early_withdraw_time_machine(self):
        # as-of 钉回提前支取之前: 支取还没发生,合同仍在保
        with ledger_dir([dep("测试行", "100000", "3.0", "12", "2023-01-10")],
                        [REN_HEADER, "2023-06-01\t测试行\twithdraw\t\t\t"]) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--as-of", "2023-05-31"])
            self.assertEqual(rc, 0)
            self.assertIn("在保", out)
            self.assertNotIn("EARLY-TAX", out)

    def test_future_renew_excluded_disclosed(self):
        with ledger_dir([dep("测试行", "100000", "2.6", "12", "2022-11-20", tag="甲")],
                        [REN_HEADER, "2023-11-20\t甲\trenew\t1.35\t12\t"]) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--as-of", "2023-11-19"])
            self.assertEqual(rc, 0)
            self.assertIn("在保", out)
            self.assertIn("未来事件", out)

    def test_future_deposit_excluded_disclosed(self):
        with ledger_dir([dep("旧钱", "100000", "3", "12", "2020-01-10"),
                         dep("新钱", "100000", "1", "12", "2030-01-10")]) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--as-of", "2021-01-01"])
            self.assertEqual(rc, 0)
            self.assertIn("未来行", out)
            self.assertIn("新钱(2030-01-10)", out)


class TestDemoNumbers(unittest.TestCase):
    """样例账本的关键数字(与独立手算对拍)。"""

    def test_report_exit4_red(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        self.assertEqual(rc, 4)
        self.assertIn("SLEEPING-DEMAND", out)
        self.assertIn("¥28,689.07", out)
        self.assertIn("躺活期 4 笔 530,000 元", out)

    def test_gonghang_832_days(self):
        rc, out, _ = run_cli(["timeline", "--dir", EXAMPLES])
        # 躺亏 = 200000×3.50%×832/365 = 15956.16
        self.assertIn("832 天", out)
        self.assertIn("¥15,956.16", out)

    def test_youchu_maturity_clamped(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        # 2020-02-29 + 60 月 = 2025-02-28(月末钳制)
        self.assertIn("2025-02-28", out)

    def test_yearly_rate(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        self.assertIn("¥15,370.00/年", out)
        self.assertIn("¥42.11/天", out)

    def test_reset_lamp_details(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        self.assertIn("掉 1.25pp", out)
        self.assertIn("掉 1.10pp", out)

    def test_prime_lamp_locks_abc(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES])
        self.assertIn("PRIME-HOLD", out)
        self.assertIn("农行 2.150%", out)

    def test_decide_values(self):
        rc, out, _ = run_cli(["decide", "--dir", EXAMPLES, "--rate", "1.25",
                              "--term", "36", "--liquid", "50000"])
        self.assertEqual(rc, 0)
        self.assertIn("= 480,000 元", out)
        self.assertIn("利息 ¥18,000.00", out)
        self.assertIn("利息 ¥720.66", out)
        self.assertIn("差额: ¥17,279.34", out)
        self.assertIn("到期 2029-08-20", out)
        self.assertIn("排除: 农行 2.150%、招行 0.950%", out)

    def test_decide_no_rate_exit3(self):
        rc, _, err = run_cli(["decide", "--dir", EXAMPLES])
        self.assertEqual(rc, 3)
        self.assertIn("--rate", err)

    def test_decide_liquid_exceeds_exit3(self):
        rc, _, _ = run_cli(["decide", "--dir", EXAMPLES, "--rate", "1.25",
                            "--liquid", "999999"])
        self.assertEqual(rc, 3)

    def test_validate_exit0(self):
        rc, out, _ = run_cli(["validate", "--dir", EXAMPLES])
        self.assertEqual(rc, 0)
        self.assertIn("逐日积分", out)
        self.assertIn("逐月游走", out)
        self.assertIn("利息对拍", out)
        self.assertIn("体检 全部通过", out)


class TestExactLines(unittest.TestCase):
    """恰线不亮——宁少报,不冤枉;翻案参数必须一路传到底。"""

    def test_reset_drop_exact_line_not_lit(self):
        # 掉 0.25pp 恰等于线: 不亮;线翻案到 0.24: 亮
        rens = [REN_HEADER, "2024-01-10\t甲\trenew\t2.75\t12\t"]
        with ledger_dir([dep("甲行", "100000", "3.0", "12", "2023-01-10", tag="甲")],
                        rens) as d:
            rc, out, _ = run_cli(["report", "--dir", d, "--as-of", "2024-06-01"])
            self.assertNotIn("RESET-DOWN", out)
            rc, out, _ = run_cli(["report", "--dir", d, "--as-of", "2024-06-01",
                                  "--reset-line", "0.24"])
            self.assertIn("RESET-DOWN", out)

    def test_red_amount_exact_not_lit(self):
        rc, _, _ = run_cli(["report", "--dir", EXAMPLES,
                            "--red-amount", "530000", "--red-yearly", "999999"])
        self.assertEqual(rc, 0)
        rc, _, _ = run_cli(["report", "--dir", EXAMPLES,
                            "--red-amount", "529999.99", "--red-yearly", "999999"])
        self.assertEqual(rc, 4)

    def test_red_yearly_exact_not_lit(self):
        rc, _, _ = run_cli(["report", "--dir", EXAMPLES,
                            "--red-amount", "999999", "--red-yearly", "15370"])
        self.assertEqual(rc, 0)
        rc, _, _ = run_cli(["report", "--dir", EXAMPLES,
                            "--red-amount", "999999", "--red-yearly", "15369.99"])
        self.assertEqual(rc, 4)

    def test_prime_exact_line_not_lit(self):
        # 合同恰 2.0% 不亮(线内),2.01% 亮
        with ledger_dir([dep("测试行", "100000", "2.0", "36", "2025-01-10")]) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertEqual(rc, 0)
            self.assertNotIn("PRIME-HOLD", out)
        with ledger_dir([dep("测试行", "100000", "2.01", "36", "2025-01-10")]) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertIn("PRIME-HOLD", out)

    def test_demand_rate_override_propagates(self):
        # 活期翻到 1.0%: 执行利率/躺亏/年化全部跟着走
        # 年化 = 200000×2.55% + 100000×1.60% + 150000×1.05% + 80000×2.575% = 10,335
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--demand-rate", "1.0"])
        self.assertIn("1.000%", out)
        self.assertIn("¥10,335.00/年", out)

    def test_reset_line_override_kills_lamp(self):
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--reset-line", "2.0"])
        self.assertNotIn("RESET-DOWN", out)

    def test_prime_line_override(self):
        # 线抬到 2.2%: 在保的农行 2.15% 不再是 PRIME
        rc, out, _ = run_cli(["report", "--dir", EXAMPLES, "--prime-line", "2.2"])
        self.assertNotIn("PRIME-HOLD", out)


class TestThinLedger(unittest.TestCase):
    """薄账分层: 空账拒答,健康账不制造警报。"""

    def test_empty_ledger_exit3(self):
        d = empty_dir()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rc_cmd in ("report", "timeline", "calendar", "decide", "validate"):
            rc, _, err = run_cli([rc_cmd, "--dir", d])
            self.assertEqual(rc, 3, rc_cmd)
            self.assertIn("空", err)

    def test_all_intact_exit0_no_lamps(self):
        with ledger_dir([dep("测试行", "100000", "1.5", "12", "2026-01-10")]) as d:
            rc, out, _ = run_cli(["report", "--dir", d])
            self.assertEqual(rc, 0)
            self.assertIn("灯: 无", out)
            self.assertIn("¥0.00", out)

    def test_asof_before_all_exit3(self):
        with ledger_dir([dep("测试行", "100000", "1.5", "12", "2026-01-10")]) as d:
            rc, _, _ = run_cli(["report", "--dir", d, "--as-of", "2025-01-01"])
            self.assertEqual(rc, 3)


class TestValidate(unittest.TestCase):
    """体检: realized 验钞与恒等式。"""

    def _copy_examples(self, fix):
        d = empty_dir()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for name in ("deposits.tsv", "renewals.tsv"):
            src = os.path.join(EXAMPLES, name)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(d, name))
        fix(d)
        return d

    def test_ghost_exit2(self):
        # 差 300 > 容差 max(1分, 应得×0.5%) = 107.64 → GHOST
        def fix(d):
            p = os.path.join(d, "deposits.tsv")
            with open(p, encoding="utf-8") as f:
                t = f.read().replace("21527.95", "21827.95")
            with open(p, "w", encoding="utf-8") as f:
                f.write(t)
        d = self._copy_examples(fix)
        rc, out, _ = run_cli(["validate", "--dir", d])
        self.assertEqual(rc, 2)
        self.assertIn("GHOST", out)
        self.assertIn("工行", out)

    def test_ghost_within_tolerance_pass(self):
        # 差 100 < 容差 107.64: 通过——银行计息细节(闰年/结息日)由容差兜底
        def fix(d):
            p = os.path.join(d, "deposits.tsv")
            with open(p, encoding="utf-8") as f:
                t = f.read().replace("21527.95", "21627.95")
            with open(p, "w", encoding="utf-8") as f:
                f.write(t)
        d = self._copy_examples(fix)
        rc, out, _ = run_cli(["validate", "--dir", d])
        self.assertEqual(rc, 0)
        self.assertIn("差 100.00", out)


class TestZeroWallClock(unittest.TestCase):
    """零墙钟: 源码无时钟;同账跨进程/跨哈希种子逐字节一致。"""

    def test_source_has_no_wall_clock(self):
        with open(CLI, encoding="utf-8") as f:
            src = f.read()
        for needle in ("today()", "now()", "time.time", "utcnow", "datetime.now"):
            self.assertNotIn(needle, src)

    def test_examples_snapshots_byte_exact(self):
        r = subprocess.run([sys.executable,
                            os.path.join(EXAMPLES, "build_examples.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_byte_identical_across_hashseeds(self):
        outputs = []
        for seed in ("1", "2", "7"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r = subprocess.run([sys.executable, CLI, "report", "--dir", EXAMPLES],
                               capture_output=True, env=env)
            self.assertEqual(r.returncode, 4)
            outputs.append(r.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])


if __name__ == "__main__":
    unittest.main()
