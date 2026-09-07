# -*- coding: utf-8 -*-
"""flat-split · 同檐 验收测试.

验收标准(README 承诺的全部转成自动化测试):
  解析层    四表载入/坏日期补零/退租早于入住/区间重叠/负·零金额/未知规则/
            悬空人名/internet 无按表先验/读数倒退/双抄表/未知房间/
            缺总表/坏 years/行尾制表符/注释空行/缺列/空账三分(缺文件·
            纯表头·零字节)/目录不存在
  分摊层    per_head 均摊/尾差吃给名字序第一人/by_meter 房间+公区
            (5 月电 126.50·88·88 手算锚点)/逐笔 Σ≡amount 闭环/月中入住
            人日/退租者段内房间账/非抄表日/首抄无上期/抄表断裂/
            as-of 剪切/缺省自锚/零墙钟逐字节/basename
  灯        LOSS 恰线不亮·超线亮·--loss-cap 翻案/SKEW 三连亮·两连不亮·
            恰 80% 不亮·单笔月跳过/report exit 4/时间机器全绿 exit 0
  assets    役月从购置次月·as-of 当月不计/品类先验月折旧+残值公式/
            --years 翻案/未知品类 n/a 不判 GAP/GAP 三笔点名+出资拆分
            尾差/回收账早于退租不亮/assets exit 4/剪回在住期 exit 0
  settle    全期零和+转账链 3 笔/--month 单月/无账单月 exit 2/互抵无转账
  validate  样例全绿 exit 0/双路径重放 ✓/房间增量>总增量 exit 2
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import flat_split  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "..", "examples")


def run(argv):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = flat_split.main(argv)
    return code, buf.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def root(self, **files):
        """写四本账;未给的表用样例缺省(仅 household/bills 必给)."""
        defaults = {
            "household.tsv": "person\troom\tstart\tend\n"
                             "老张\t主卧\t2025-03-01\t\n"
                             "小王\t次卧\t2025-03-01\t\n"
                             "小马\t小卧\t2025-03-01\t\n",
            "bills.tsv": "date\tcategory\tamount\trule\tpayer\n",
        }
        defaults.update(files)
        for name, content in defaults.items():
            with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
                f.write(content)
        return self.tmp

    def write(self, name, content):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.join(self.tmp, name)


# ---------------------------------------------------------------- 解析层
class TestParse(Base):
    def test_examples_load(self):
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2026-03-10"])
        self.assertEqual(code, 4)          # 样例带灯属设计内
        self.assertIn("名册 4 人(在住 3 人)", out)
        self.assertIn("账单 23 笔", out)
        self.assertIn("资产 4 项", out)

    def test_missing_household(self):
        p = os.path.join(self.tmp, "nohouse")
        os.makedirs(p)
        with open(os.path.join(p, "bills.tsv"), "w", encoding="utf-8") as f:
            f.write("date\tcategory\tamount\trule\tpayer\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("household.tsv", err)

    def test_root_not_exist(self):
        code, _, err = run(["report", os.path.join(self.tmp, "ghost")])
        self.assertEqual(code, 2)

    def test_household_bad_date_zero_pad(self):
        p = self.root(**{"household.tsv":
                         "person\troom\tstart\tend\n老张\t主卧\t2025-3-1\t\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("补零", err)

    def test_household_end_before_start(self):
        p = self.root(**{"household.tsv":
                         "person\troom\tstart\tend\n老张\t主卧\t2025-03-01\t2024-01-01\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("早于入住", err)

    def test_household_overlapping_spans(self):
        p = self.root(**{"household.tsv":
                         "person\troom\tstart\tend\n"
                         "老张\t主卧\t2025-03-01\t2025-09-01\n"
                         "老张\t次卧\t2025-08-01\t\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("重叠", err)

    def test_bill_bad_date(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-13-01\twater\t90\tper_head\t老张\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)

    def test_bill_negative_amount(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t-90\tper_head\t老张\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("正数", err)

    def test_bill_zero_amount(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t0\tper_head\t老张\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)

    def test_bill_unknown_rule(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tby_room\t老张\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("未知分摊规则", err)

    def test_bill_payer_not_in_roster(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tper_head\t路人甲\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("不在名册", err)

    def test_bill_by_meter_no_prior(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\tinternet\t90\tby_meter\t老张\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("无按表分摊先验", err)

    def test_meter_reading_rollback(self):
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-01\telectricity\t55\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-04-01\telectricity\t_total\t100\n"
               "2025-05-01\telectricity\t主卧\t90\n"
               "2025-05-01\telectricity\t_total\t155\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("倒退", err)

    def test_meter_duplicate_reading(self):
        p = self.root(
            **{"meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-04-01\telectricity\t主卧\t105\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("重复抄表", err)

    def test_meter_unknown_room(self):
        p = self.root(
            **{"meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t储物间\t100\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("不在名册", err)

    def test_meter_room_without_total(self):
        p = self.root(
            **{"meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-05-01\telectricity\t主卧\t160\n"
               "2025-05-01\telectricity\t_total\t255\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("同日总表", err)

    def test_asset_bad_cost(self):
        p = self.root(**{"assets.tsv":
                         "date\tname\tcategory\tcost\tfunder\tyears\n"
                         "2025-03-01\t洗衣机\t洗衣机\t-1\t老张\t\n"})
        code, _, err = run(["assets", p])
        self.assertEqual(code, 2)

    def test_asset_unknown_funder(self):
        p = self.root(**{"assets.tsv":
                         "date\tname\tcategory\tcost\tfunder\tyears\n"
                         "2025-03-01\t洗衣机\t洗衣机\t100\t路人甲\t\n"})
        code, _, err = run(["assets", p])
        self.assertEqual(code, 2)
        self.assertIn("不在名册", err)

    def test_asset_bad_years(self):
        for y in ("0", "-3", "abc"):
            p = self.root(**{"assets.tsv":
                             f"date\tname\tcategory\tcost\tfunder\tyears\n"
                             f"2025-03-01\t洗衣机\t洗衣机\t100\t老张\t{y}\n"})
            code, _, err = run(["assets", p])
            self.assertEqual(code, 2, y)
            self.assertIn("折旧年限", err)

    def test_trailing_tab_tolerated(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tper_head\t老张\t\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertIn("90.00", out)

    def test_comments_and_blank_lines(self):
        p = self.root(**{"bills.tsv":
                         "# 记账从四月开始\n"
                         "\n"
                         "date\tcategory\tamount\trule\tpayer\n"
                         "\n"
                         "2025-04-05\twater\t90\tper_head\t老张\n"})
        code, _, _ = run(["report", p])
        self.assertEqual(code, 0)

    def test_missing_column(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tper_head\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("缺列", err)

    def test_empty_ledger_no_bills_file(self):
        p = self.root()
        os.remove(os.path.join(p, "bills.tsv"))
        code, _, err = run(["report", p])
        self.assertEqual(code, 3)
        self.assertIn("还没开始记", err)

    def test_empty_ledger_header_only(self):
        p = self.root()
        code, _, _ = run(["report", p])
        self.assertEqual(code, 3)

    def test_empty_ledger_zero_bytes(self):
        p = self.root(**{"bills.tsv": ""})
        code, _, _ = run(["report", p])
        self.assertEqual(code, 3)

    def test_empty_ledger_comments_only(self):
        p = self.root(**{"bills.tsv": "# 只有注释\n\n"})
        code, _, _ = run(["report", p])
        self.assertEqual(code, 3)


# ---------------------------------------------------------------- 分摊层
class TestAllocate(Base):
    def test_per_head_even(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t96\tper_head\t小王\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertIn("应付 小王 32.00  小马 32.00  老张 32.00", out)

    def test_per_head_remainder_name_order(self):
        """88/3:尾差吃给名字序(Unicode 码点)第一人小王."""
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t88\tper_head\t老张\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertIn("应付 小王 29.34  小马 29.33  老张 29.33", out)

    def test_by_meter_rooms_and_public(self):
        """样例 5 月电:房间 121/82.50/82.50 + 公区 16.50→5.50×3."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-05-31"])
        self.assertEqual(code, 0)
        self.assertIn("应付 小王 117.34  小马 117.33  老张 155.83", out)

    def test_by_meter_per_bill_closure(self):
        """逐笔 Σ(逐人) ≡ amount:逐月合计与账单总额在月粒度全等."""
        code, out, _ = run(["validate", EXAMPLES])
        self.assertEqual(code, 0)
        self.assertIn("Σ逐人应付 7179.75 ≡ Σ账单 7179.75 : ✓", out)

    def test_midmonth_join_prorated(self):
        """阿花 2026-02-15 入住:3 月水费三人各 1/3(整月在住)."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2026-03-10"])
        self.assertIn("── 2026-03", out)
        self.assertIn("阿花 179.84", out)

    def test_departed_still_owns_segment_bill(self):
        """2-1 账单:小卧段内(12-01→02-01)小马住 51 天,房间账归他."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2026-03-10"])
        self.assertIn("── 2026-02", out)
        self.assertIn("小马 132.93", out)

    def test_by_meter_bill_not_on_reading_day(self):
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-02\telectricity\t55\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-04-01\telectricity\t_total\t100\n"
               "2025-05-01\telectricity\t主卧\t160\n"
               "2025-05-01\telectricity\t_total\t155\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("不是 electricity 的抄表日", err)

    def test_by_meter_first_reading_no_prior(self):
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-04-01\telectricity\t55\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-04-01\telectricity\t_total\t100\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("没有上一期读数", err)

    def test_by_meter_broken_readings(self):
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-01\telectricity\t55\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t次卧\t100\n"      # 主卧缺 04-01
               "2025-04-01\telectricity\t_total\t200\n"
               "2025-05-01\telectricity\t主卧\t160\n"
               "2025-05-01\telectricity\t次卧\t160\n"
               "2025-05-01\telectricity\t_total\t320\n"})
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("读数不全", err)

    def test_asof_scissors(self):
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-05-31"])
        self.assertEqual(code, 0)
        self.assertIn("账单 3 笔", out)
        self.assertNotIn("2025-06", out)

    def test_default_asof_anchors_ledger_max(self):
        code, out, _ = run(["report", EXAMPLES])
        self.assertIn("as-of 2026-03-10", out)

    def test_zero_wall_clock_byte_identical(self):
        _, out1, _ = run(["report", EXAMPLES])
        _, out2, _ = run(["report", EXAMPLES])
        self.assertEqual(out1, out2)

    def test_report_prints_basename_only(self):
        code, out, _ = run(["report", EXAMPLES])
        self.assertIn("— examples/", out)
        self.assertNotIn("/Users/", out)


# ---------------------------------------------------------------- 灯
class TestGates(Base):
    def _meter_root(self, loss_reading, cap=None):
        """主卧走 100→160,总表走 100→160+loss_reading."""
        bills = ("date\tcategory\tamount\trule\tpayer\n"
                 "2025-05-01\telectricity\t33\tby_meter\t老张\n")
        meters = ("date\tcategory\troom\treading\n"
                  "2025-04-01\telectricity\t主卧\t100\n"
                  "2025-04-01\telectricity\t次卧\t100\n"
                  "2025-04-01\telectricity\t_total\t200\n"
                  "2025-05-01\telectricity\t主卧\t160\n"
                  "2025-05-01\telectricity\t次卧\t160\n"
                  f"2025-05-01\telectricity\t_total\t{420 + loss_reading}\n")
        kw = {"bills.tsv": bills, "meters.tsv": meters}
        p = self.root(**kw)
        if cap:
            return p + ["--loss-cap", cap]
        return p

    def test_loss_exact_line_not_lit(self):
        """水 12% 线:房间增 88,总增 100 → 损耗恰 12.00% 不亮."""
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-05\twater\t33\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-05\twater\t主卧\t100\n"
               "2025-04-05\twater\t次卧\t100\n"
               "2025-04-05\twater\t_total\t200\n"
               "2025-05-05\twater\t主卧\t150\n"
               "2025-05-05\twater\t次卧\t138\n"
               "2025-05-05\twater\t_total\t300\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertNotIn("🔴 LOSS", out)
        self.assertIn("12.00%", out)

    def test_loss_over_line_lit(self):
        """同构造,总增 105 → 损耗 17/105=16.19% 亮."""
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-05\twater\t33\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-05\twater\t主卧\t100\n"
               "2025-04-05\twater\t次卧\t100\n"
               "2025-04-05\twater\t_total\t200\n"
               "2025-05-05\twater\t主卧\t150\n"
               "2025-05-05\twater\t次卧\t138\n"
               "2025-05-05\twater\t_total\t305\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 4)
        self.assertIn("🔴 LOSS", out)

    def test_loss_below_and_over(self):
        """两本账:损耗 5%不亮 vs 10.94%亮(样例 7→8 月段)."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-06-30"])
        self.assertEqual(code, 0)                    # 4→5 段 5.45% 5→6 段 5.30%
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-08-31"])
        self.assertEqual(code, 4)
        self.assertIn("🔴 LOSS", out)
        self.assertIn("10.94%", out)

    def test_loss_cap_override(self):
        """--loss-cap 0.30:10.94% 段不再亮(SKEW 三连仍亮属设计内)."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-08-31",
                            "--loss-cap", "0.30"])
        self.assertEqual(code, 4)          # SKEW 老张 6/7/8 三连
        self.assertNotIn("🔴 LOSS", out)
        self.assertIn("🔴 SKEW", out)

    def test_skew_three_months_lit(self):
        code, out, _ = run(["report", EXAMPLES])
        self.assertIn("🔴 SKEW", out)
        self.assertIn("老张", out)
        self.assertIn("2025-06", out)

    def test_skew_two_months_not_lit(self):
        """样例 10-11 月小王连续两月 100%,不足三连不点名(老张 6/7/8 在)."""
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-11-30"])
        self.assertIn("🔴 SKEW", out)              # 老张三连
        self.assertNotIn("小王:2025-10", out)      # 小王两连不点名

    def test_skew_exact_cap_not_lit(self):
        """恰 80.00% 不亮:两笔 [80,20] → top 80.00%."""
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-01\twater\t80\tper_head\t老张\n"
                         "2025-04-02\tinternet\t20\tper_head\t小王\n"
                         "2025-05-01\twater\t80\tper_head\t老张\n"
                         "2025-05-02\tinternet\t20\tper_head\t小王\n"
                         "2025-06-01\twater\t80\tper_head\t老张\n"
                         "2025-06-02\tinternet\t20\tper_head\t小王\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertNotIn("🔴 SKEW", out)

    def test_skew_single_bill_month_skipped(self):
        """单笔月必 100% 但不参与(样本 1 无意义)."""
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-01\twater\t80\tper_head\t老张\n"
                         "2025-05-01\twater\t80\tper_head\t老张\n"
                         "2025-06-01\twater\t80\tper_head\t老张\n"})
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertNotIn("🔴 SKEW", out)

    def test_report_exit4_with_lights(self):
        code, out, _ = run(["report", EXAMPLES])
        self.assertEqual(code, 4)
        self.assertIn("── 灯", out)

    def test_time_machine_all_green(self):
        code, out, _ = run(["report", EXAMPLES, "--as-of", "2025-05-31"])
        self.assertEqual(code, 0)
        self.assertIn("全灭", out)


# ---------------------------------------------------------------- assets
class TestAssets(Base):
    def test_usage_starts_month_after_purchase(self):
        """热水壶 2026-02-20 购置:as-of 2026-03-10 前一整月=02 → 役月 0."""
        code, out, _ = run(["assets", EXAMPLES])
        self.assertIn("役月 0", out)
        self.assertIn("残值 ¥159.00", out)

    def test_builtin_years_and_residual(self):
        code, out, _ = run(["assets", EXAMPLES])
        self.assertIn("折旧 8 年直线:月 31.25 × 役月 11 = 343.75  残值 ¥2656.25", out)
        self.assertIn("折旧 5 年直线:月 20.00 × 役月 11 = 220.00  残值 ¥980.00", out)

    def test_ledger_years_override_prior(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t60\tper_head\t老张\n",
                         "assets.tsv":
                         "date\tname\tcategory\tcost\tfunder\tyears\n"
                         "2025-03-01\t洗衣机\t洗衣机\t2400\t老张\t4\n"})
        code, out, _ = run(["assets", p, "--as-of", "2025-05-31"])
        self.assertEqual(code, 0)
        self.assertIn("折旧 4 年直线:月 50.00 × 役月 1", out)

    def test_unknown_category_na(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t60\tper_head\t老张\n",
                         "assets.tsv":
                         "date\tname\tcategory\tcost\tfunder\tyears\n"
                         "2025-03-01\t水晶灯\t水晶灯\t800\t老张\t\n"})
        code, out, _ = run(["assets", p])
        self.assertEqual(code, 0)
        self.assertIn("无折旧先验:残值 n/a,不判 GAP", out)

    def test_gap_named_with_funder_split(self):
        code, out, _ = run(["assets", EXAMPLES])
        self.assertEqual(code, 4)
        self.assertIn("✗ 小马(2025-04~2026-01 共 10 月) ¥104.17 → 老张 104.17", out)
        self.assertIn("¥27.71 → 小王 27.71", out)
        self.assertIn("¥66.67 → 小王 22.23  小马 22.22  老张 22.22", out)

    def test_gap_exit4(self):
        code, _, _ = run(["assets", EXAMPLES])
        self.assertEqual(code, 4)

    def test_recover_bill_before_departure_covers(self):
        """小马退租前就有回收账 → GAP 不亮(账在动,历史滚存视为结清)."""
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-04-10\t洗衣机\t40\tper_head\t老张\n",
               "assets.tsv":
               "date\tname\tcategory\tcost\tfunder\tyears\n"
               "2025-03-01\t洗衣机\t洗衣机\t3000\t老张\t\n"})
        # 小马未退租(样例名册无 end)→ 无 departed,本就无 GAP;
        # 再造一个已退租者:
        with open(os.path.join(p, "household.tsv"), "w", encoding="utf-8") as f:
            f.write("person\troom\tstart\tend\n"
                    "老张\t主卧\t2025-03-01\t\n"
                    "小马\t小卧\t2025-03-01\t2025-09-30\n")
        code, out, _ = run(["assets", p])
        self.assertEqual(code, 0)
        self.assertIn("GAP 审计干净", out)

    def test_gap_after_departure_recover_too_late(self):
        """回收账晚于退租日:补记的账摊不到走了的人 → GAP 亮."""
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-10-10\t洗衣机\t40\tper_head\t老张\n",
               "assets.tsv":
               "date\tname\tcategory\tcost\tfunder\tyears\n"
               "2025-03-01\t洗衣机\t洗衣机\t3000\t老张\t\n"})
        with open(os.path.join(p, "household.tsv"), "w", encoding="utf-8") as f:
            f.write("person\troom\tstart\tend\n"
                    "老张\t主卧\t2025-03-01\t\n"
                    "小马\t小卧\t2025-03-01\t2025-09-30\n")
        code, out, _ = run(["assets", p])
        self.assertEqual(code, 4)
        self.assertIn("🔴 GAP", out)
        self.assertIn("小马", out)

    def test_assets_scissor_to_occupied_period(self):
        """钉回小马未走时:无 departed → 无 GAP → exit 0."""
        code, _, _ = run(["assets", EXAMPLES, "--as-of", "2025-05-31"])
        self.assertEqual(code, 0)

    def test_no_assets_message(self):
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tper_head\t老张\n"})
        code, out, _ = run(["assets", p])
        self.assertEqual(code, 0)
        self.assertIn("没有公共资产", out)


# ---------------------------------------------------------------- settle
class TestSettle(Base):
    def test_full_period_zero_sum_chain(self):
        code, out, _ = run(["settle", EXAMPLES])
        self.assertEqual(code, 0)
        self.assertIn("小马 → 老张  ¥600.76", out)
        self.assertIn("小王 → 老张  ¥221.19", out)
        self.assertIn("阿花 → 老张  ¥81.84", out)
        self.assertIn("Σ净额 0.00", out)

    def test_settle_month(self):
        code, out, _ = run(["settle", EXAMPLES, "--month", "2026-02"])
        self.assertEqual(code, 0)
        self.assertIn("老张 → 小王  ¥373.54", out)
        self.assertIn("小马 → 小王  ¥132.93", out)

    def test_settle_month_no_bills(self):
        code, _, err = run(["settle", EXAMPLES, "--month", "2025-01"])
        self.assertEqual(code, 2)

    def test_settle_month_bad_format(self):
        code, _, err = run(["settle", EXAMPLES, "--month", "2026-2"])
        self.assertEqual(code, 2)

    def test_settle_mutual_offset_no_transfer(self):
        """三人各垫一笔等额账(90 可整除):净额全零,没有一笔转账."""
        p = self.root(**{"bills.tsv":
                         "date\tcategory\tamount\trule\tpayer\n"
                         "2025-04-05\twater\t90\tper_head\t老张\n"
                         "2025-04-06\tinternet\t90\tper_head\t小王\n"
                         "2025-04-07\tproperty\t90\tper_head\t小马\n"})
        code, out, _ = run(["settle", p])
        self.assertEqual(code, 0)
        self.assertIn("全员两清", out)


# ---------------------------------------------------------------- validate
class TestValidate(Base):
    def test_validate_examples_green(self):
        code, out, _ = run(["validate", EXAMPLES])
        self.assertEqual(code, 0)
        self.assertIn("账本体检通过", out)
        self.assertIn("双路径重放(管线 vs 独立重放)逐人全等: ✓", out)
        self.assertIn("Σ净额 0.00 ≡ 0(清算零和): ✓", out)
        self.assertIn("残值 2656.25", out)

    def test_validate_rooms_exceed_total(self):
        """房间增量 > 总增量:表不对,validate 判 ✗ exit 2."""
        p = self.root(
            **{"bills.tsv":
               "date\tcategory\tamount\trule\tpayer\n"
               "2025-05-01\telectricity\t55\tby_meter\t老张\n",
               "meters.tsv":
               "date\tcategory\troom\treading\n"
               "2025-04-01\telectricity\t主卧\t100\n"
               "2025-04-01\telectricity\t次卧\t100\n"
               "2025-04-01\telectricity\t_total\t200\n"
               "2025-05-01\telectricity\t主卧\t200\n"
               "2025-05-01\telectricity\t次卧\t200\n"
               "2025-05-01\telectricity\t_total\t300\n"})
        code, out, _ = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("房间增量超过总增量", out)

    def test_validate_residual_formula(self):
        code, out, _ = run(["validate", EXAMPLES])
        self.assertIn("洗衣机:残值 2656.25 ≡ cost 3000.00 − 月折旧 31.25×役月 11 : ✓",
                      out)


# ---------------------------------------------------------------- 样例快照
class TestSnapshots(Base):
    def test_snapshots_match_build_examples(self):
        import subprocess
        done = subprocess.run(
            [sys.executable, os.path.join(EXAMPLES, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(done.returncode, 0,
                         f"快照与构建器不一致:\n{done.stdout}{done.stderr}")


if __name__ == "__main__":
    unittest.main()
