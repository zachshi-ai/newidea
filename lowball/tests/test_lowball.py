# -*- coding: utf-8 -*-
"""低价签验收测试:解析层 / 四分类恒等式 / 漏项审计 / 幻觉指数 / 诱饵×开口 /
宰客单价 / 签字门禁 / THIN 拒答 / 基线覆盖 / 逐字节快照."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import lowball  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")
QUOTE = os.path.join(EXAMPLES, "quote.tsv")
ADDONS = os.path.join(EXAMPLES, "addons.tsv")
QUOTEGOOD = os.path.join(EXAMPLES, "quote-good.tsv")

# 示例账本手算常量(合同 93,002 · 增项 51,236 · 结算 144,238)
Q_TOTAL = 93002.0
A_TOTAL = 51236.0
KIND_TOTALS = {"upgrade": 10070.0, "forced": 13810.0, "drift": 12616.0, "padded": 14740.0}
MID_GAP = 26322.21          # Σ 漏项中位预估(浮点容差内)
FLOOR = 119324.0            # 真实底价(合同 + 漏项中位)
HALLUC = 0.283              # 幻觉指数 28.3%


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = lowball.main(argv)
    return code, buf.getvalue()


class Fixture(unittest.TestCase):
    """临时目录里摆好账本。"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.quote = os.path.join(self.dir.name, "quote.tsv")
        self.addons = os.path.join(self.dir.name, "addons.tsv")
        shutil_copy(QUOTE, self.quote)
        shutil_copy(ADDONS, self.addons)

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def shutil_copy(src, dst):
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(text)


# --------------------------------------------------------------- 解析层
class Parse(Fixture):
    def test_examples_load(self):
        quote = lowball.parse_quote(QUOTE)
        addons = lowball.parse_addons(ADDONS)
        good = lowball.parse_quote(QUOTEGOOD)
        self.assertEqual(len(quote), 21)
        self.assertEqual(len(addons), 12)
        self.assertEqual(len(good), 30)

    def test_missing_column(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\tnote\nX\t1\t项\t5\t5\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_short_row(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\nX\t1\t项\t5\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_empty_item(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\n\t1\t项\t5\t5\tfixed\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_duplicate_item(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\n"
                               "X\t1\t项\t5\t5\tfixed\t-\nX\t2\t项\t5\t10\tfixed\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_non_numeric_qty(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\nX\tmany\t项\t5\t5\tfixed\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_negative_price(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\nX\t1\t项\t-5\t-5\tfixed\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_amount_inconsistent(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\nX\t2\t项\t5\t5\tfixed\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_bad_est(self):
        self.write(self.quote, "item\tqty\tunit\tunit_price\tamount\test\tnote\nX\t1\t项\t5\t5\tmaybe\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_bad_kind(self):
        self.write(self.addons, "item\tkind\tqty\tunit\tunit_price\tamount\tnote\nX\tother\t1\t项\t5\t5\t-\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_addons(self.addons)

    def test_empty_ledger(self):
        self.write(self.quote, "# 只有注释\n")
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(self.quote)

    def test_missing_file(self):
        with self.assertRaises(lowball.Broken):
            lowball.parse_quote(os.path.join(self.dir.name, "nope.tsv"))

    def test_missing_file_exits_2(self):
        code, out = run(["audit", os.path.join(self.dir.name, "nope.tsv"), self.addons])
        self.assertEqual(code, 2)
        self.assertIn("账本损坏", out)


# --------------------------------------------------------------- audit / 恒等式
class Audit(Fixture):
    def test_identity_totals(self):
        addons = lowball.parse_addons(ADDONS)
        totals, counts = lowball.classify_totals(addons)
        self.assertAlmostEqual(sum(totals.values()), A_TOTAL, places=6)
        for k, v in KIND_TOTALS.items():
            self.assertAlmostEqual(totals[k], v, places=6)
        self.assertEqual(sum(counts.values()), 12)

    def test_settlement_identity(self):
        quote = lowball.parse_quote(QUOTE)
        addons = lowball.parse_addons(ADDONS)
        self.assertAlmostEqual(sum(q.amount for q in quote), Q_TOTAL, places=6)
        self.assertAlmostEqual(sum(q.amount for q in quote) + sum(a.amount for a in addons),
                               144238.0, places=6)

    def test_audit_red_exit4(self):
        code, out = run(["audit", self.quote, self.addons])
        self.assertEqual(code, 4)
        self.assertIn("+55.1%", out)
        self.assertIn("¥144,238", out)
        self.assertIn("2.19x", out)
        self.assertIn("1.58x", out)
        self.assertIn("2.40x", out)
        self.assertIn("残差 0.00", out)

    def test_rate_cap_override(self):
        # cap 调到 0.6:率线让位,但宰客单价独立顶住红线
        code, out = run(["audit", self.quote, self.addons, "--cap", "0.6"])
        self.assertEqual(code, 4)
        self.assertIn("宰客单价", out)

    def test_upgrade_only_yellow(self):
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "壁布升级\tupgrade\t1\t项\t12000\t12000\t自己要的\n"
                   "灯具升级\tupgrade\t1\t项\t6000\t6000\t自己要的\n"
                   "开关升级\tupgrade\t1\t项\t4500\t4500\t自己要的\n")
        code, out = run(["audit", self.quote, self.addons])
        self.assertEqual(code, 1)
        self.assertIn("黄线", out)

    def test_thin_addons(self):
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "壁布升级\tupgrade\t1\t项\t800\t800\t-\n")
        code, out = run(["audit", self.quote, self.addons])
        self.assertEqual(code, 3)
        self.assertIn("THIN", out)

    def test_drift_math(self):
        quote = lowball.parse_quote(QUOTE)
        addons = lowball.parse_addons(ADDONS)
        pairs = lowball.drift_pairs(addons, quote, lowball.load_baselines(type("A", (), {"baselines": None})()))
        self.assertEqual(len(pairs), 1)
        a, q, final, ratio = pairs[0]
        self.assertAlmostEqual(final, 612.0, places=6)
        self.assertAlmostEqual(ratio, 612.0 / 280.0, places=6)

    def test_drift_orphan_broken(self):
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "泥工量差\tdrift\t100\t项\t50\t5000\t无处挂靠\n"
                   "防水补\tforced\t1\t项\t100\t100\t-\n"
                   "搬运\tpadded\t1\t项\t100\t100\t-\n")
        code, out = run(["audit", self.quote, self.addons])
        self.assertEqual(code, 2)
        self.assertIn("挂靠不到", out)

    def test_open_items_reported(self):
        code, out = run(["validate", self.quote, self.addons])
        self.assertIn("开口条目:水电改造", out)


# --------------------------------------------------------------- gaps / judge
class Gaps(Fixture):
    def test_missing_counts(self):
        quote = lowball.parse_quote(QUOTE)
        bl = lowball.load_baselines(type("A", (), {"baselines": None})())
        idx, rows, mid, lo, hi, nonpct = lowball.hallucination(quote, bl)
        uni = [b for b, _, _ in rows if b["cond"] == "universal"]
        con = [b for b, _, _ in rows if b["cond"] == "conditional"]
        self.assertEqual(len(uni), 6)
        self.assertEqual(len(con), 3)
        self.assertAlmostEqual(nonpct, Q_TOTAL, places=4)

    def test_hallucination_index(self):
        quote = lowball.parse_quote(QUOTE)
        bl = lowball.load_baselines(type("A", (), {"baselines": None})())
        idx, rows, mid, lo, hi, nonpct = lowball.hallucination(quote, bl)
        self.assertAlmostEqual(idx, HALLUC, places=2)
        self.assertAlmostEqual(mid, MID_GAP, places=0)
        # 恒等式:底价 = 合同 + 中位预估
        self.assertAlmostEqual(Q_TOTAL + mid, FLOOR, places=0)

    def test_gaps_red_exit4(self):
        code, out = run(["gaps", self.quote])
        self.assertEqual(code, 4)
        self.assertIn("28.3%", out)
        self.assertIn("¥119,324", out)
        self.assertIn("universal 漏项 6 项", out)

    def test_gates_are_tunable(self):
        code, out = run(["gaps", self.quote, "--gate-universal", "10"])
        # 10 扇 universal 门只留幻觉指数触发 → 仍是红线
        self.assertEqual(code, 4)
        self.assertIn("幻觉指数", out)

    def test_good_quote_clean(self):
        code, out = run(["gaps", QUOTEGOOD])
        self.assertEqual(code, 0)
        self.assertIn("幻觉指数 0.0%", out)

    def test_thin_quote(self):
        self.write(self.quote,
                   "item\tqty\tunit\tunit_price\tamount\test\tnote\n"
                   "拆除\t1\t项\t100\t100\tfixed\t-\n"
                   "水电\t1\t项\t100\t100\tfixed\t-\n")
        code, out = run(["gaps", self.quote])
        self.assertEqual(code, 3)
        code2, out2 = run(["judge", self.quote])
        self.assertEqual(code2, 3)

    def test_judge_red_exit4(self):
        code, out = run(["judge", self.quote])
        self.assertEqual(code, 4)
        self.assertIn("不签", out)
        self.assertIn("诱饵×开口", out)
        self.assertIn("¥38/m", out)

    def test_judge_good_exit0(self):
        code, out = run(["judge", QUOTEGOOD])
        self.assertEqual(code, 0)
        self.assertIn("诚实的贵", out)

    def test_baselines_override_flips_verdict(self):
        # 行情抬到 140–180:B 单 55 的水电也翻诱饵 → 先验可覆盖,判罚跟行情
        bl = os.path.join(self.dir.name, "base.tsv")
        self.write(bl, "key\taliases\tlow\thigh\tunit\tcond\ttypical\n"
                       "水电改造\t水电\t140\t180\t/m\tconditional\t280\n")
        code, _ = run(["judge", QUOTEGOOD, "--baselines", bl])
        self.assertEqual(code, 4)

    def test_baselines_low_gt_high_broken(self):
        bl = os.path.join(self.dir.name, "base.tsv")
        self.write(bl, "key\taliases\tlow\thigh\tunit\tcond\ttypical\n"
                       "水电\t水电\t90\t45\t/m\tconditional\t280\n")
        code, out = run(["judge", self.quote, "--baselines", bl])
        self.assertEqual(code, 2)


# --------------------------------------------------------------- prices
class Prices(Fixture):
    def test_kill_and_bait(self):
        quote = lowball.parse_quote(QUOTE)
        addons = lowball.parse_addons(ADDONS)
        bl = lowball.load_baselines(type("A", (), {"baselines": None})())
        kills = lowball.kill_lines(addons, quote, bl)
        names = {a.name: m for a, b, m, ap in kills}
        self.assertAlmostEqual(names["墙面找平(误差超范围)"], 95 / 60, places=6)
        self.assertAlmostEqual(names["材料搬运上楼"], 2.4, places=6)
        ob = lowball.open_bait(quote, bl)
        self.assertEqual(len(ob), 1)
        self.assertAlmostEqual(ob[0][2], 38 / 45, places=6)

    def test_prices_red_exit4(self):
        code, out = run(["prices", self.quote, self.addons])
        self.assertEqual(code, 4)
        self.assertIn("宰客(1.58x 上沿)", out)
        self.assertIn("宰客(2.40x 上沿)", out)
        self.assertIn("诱饵(0.84x 下沿)", out)

    def test_pct_rows_audited_by_ratio(self):
        code, out = run(["prices", self.quote, self.addons])
        self.assertIn("8.0% 合同额", out)
        self.assertIn("3.5% 合同额", out)

    def test_unbaselined_rows_pass_through(self):
        code, out = run(["prices", self.quote, self.addons])
        self.assertIn("无常识基线", out)
        self.assertIn("主卫墙砖换购升级", out)

    def test_prices_clean_exit0(self):
        # 全区间内构造 → 绿
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "防水(补报)\tforced\t14\t㎡\t60\t840\t区间内\n"
                   "闭水\tforced\t2\t次\t200\t400\t区间内\n"
                   "垃圾清运\tforced\t1\t项\t2000\t2000\t区间内\n")
        code, out = run(["prices", self.quote, self.addons])
        self.assertEqual(code, 0)

    def test_prices_thin(self):
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "防水\tforced\t1\t项\t100\t100\t-\n")
        code, out = run(["prices", self.quote, self.addons])
        self.assertEqual(code, 3)


# --------------------------------------------------------------- sign
class Sign(Fixture):
    def test_kill_exit4(self):
        code, out = run(["sign", self.quote, "--item", "墙面找平(误差超范围)",
                         "--qty", "96", "--price", "95", "--unit", "元/㎡"])
        self.assertEqual(code, 4)
        self.assertIn("1.58x", out)
        self.assertIn("宰客价", out)

    def test_in_range_exit0(self):
        code, out = run(["sign", self.quote, "--item", "卫生间防水(两遍)",
                         "--qty", "14", "--price", "70", "--unit", "㎡"])
        self.assertEqual(code, 0)
        self.assertIn("区间内", out)

    def test_bait_exit1_with_open_hint(self):
        code, out = run(["sign", self.quote, "--item", "水电改造量差",
                         "--qty", "100", "--price", "38", "--unit", "m"])
        self.assertEqual(code, 1)
        self.assertIn("低于常识", out)
        self.assertIn("开口条目", out)

    def test_recommended_row_is_tsv(self):
        code, out = run(["sign", self.quote, "--item", "卫生间防水(两遍)",
                         "--qty", "14", "--price", "70", "--unit", "㎡"])
        line = [ln for ln in out.splitlines() if ln.startswith("    卫生间防水(两遍)\t")][0]
        cols = line.strip().split("\t")
        self.assertEqual(len(cols), 7)
        self.assertEqual(cols[1], "forced")
        self.assertEqual(cols[5], "980")

    def test_no_baseline_passes(self):
        code, out = run(["sign", self.quote, "--item", "火星砖定制",
                         "--qty", "1", "--price", "5000", "--unit", "项"])
        self.assertEqual(code, 0)
        self.assertIn("无匹配基线", out)

    def test_contract_crossref(self):
        # 同 key 条目在报价单中存在 → 给出倍数对照
        code, out = run(["sign", self.quote, "--item", "乳胶漆加一遍",
                         "--qty", "100", "--price", "30", "--unit", "㎡"])
        self.assertIn("「墙面乳胶漆(两底两面)」单价 ¥48", out)
        self.assertIn("0.62x", out)


# --------------------------------------------------------------- 边界与数学
class MathEdges(Fixture):
    def _bl(self):
        return lowball.load_baselines(type("A", (), {"baselines": None})())

    def test_gap_range_brackets_mid(self):
        quote = lowball.parse_quote(QUOTE)
        idx, rows, mid, lo, hi, nonpct = lowball.hallucination(quote, self._bl())
        self.assertLess(lo, mid)
        self.assertLess(mid, hi)
        self.assertGreater(idx, 0)

    def test_gap_estimate_pct_math(self):
        b = {"key": "管理费", "aliases": ["管理费"], "low": 0.04, "high": 0.08,
             "unit": "pct", "cond": "universal", "typical": 1}
        self.assertAlmostEqual(lowball.gap_estimate(b, 100000.0), 6000.0, places=6)

    def test_closed_item_never_open_bait(self):
        quote = lowball.parse_quote(QUOTE)
        for q in quote:
            q.est = "fixed"          # 全闭口:诱饵单价仍在,杀局不再成立
        ob = lowball.open_bait(quote, self._bl())
        self.assertEqual(len(ob), 0)

    def test_judge_lists_all_missing_keys(self):
        code, out = run(["judge", self.quote])
        for key in ("防水", "闭水试验", "找平", "垃圾清运", "成品保护",
                    "管理费", "税票", "开荒保洁", "搬运上楼"):
            self.assertIn(key, out)

    def test_pct_over_ceiling_flagged(self):
        # 管理费补收到 12% 合同额:比例类超出上沿 → ▲ 上沿之上
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "防水\tforced\t14\t㎡\t60\t840\t-\n"
                   "闭水\tforced\t2\t次\t200\t400\t-\n"
                   "垃圾清运\tforced\t1\t项\t2000\t2000\t-\n"
                   "管理费\tpadded\t1\t项\t11160\t11160\t12% 合同额\n")
        code, out = run(["prices", self.quote, self.addons])
        self.assertIn("▲ 上沿之上", out)
        self.assertEqual(code, 0)      # 比例类不参与宰客红线,只落位

    def test_audit_all_upgrade_within_lines_exit0(self):
        code, out = run(["audit", self.quote, self.addons,
                         "--cap", "0.9"])
        self.assertEqual(code, 4)      # 宰客单价独立红线,不受 cap 调高影响

    def test_quote_total_constant(self):
        quote = lowball.parse_quote(QUOTEGOOD)
        self.assertAlmostEqual(sum(q.amount for q in quote), 130012.0, places=6)

    def test_baselines_custom_file_used(self):
        bl = os.path.join(self.dir.name, "base.tsv")
        self.write(bl, "key\taliases\tlow\thigh\tunit\tcond\ttypical\n"
                       "水电\t水电\t45\t90\t/m\tconditional\t280\n")
        parsed = lowball.parse_baselines(bl)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["key"], "水电")


# --------------------------------------------------------------- validate
class Validate(Fixture):
    def test_clean_exit0(self):
        code, out = run(["validate", self.quote, self.addons])
        self.assertEqual(code, 0)
        self.assertIn("全部通过", out)

    def test_orphan_drift_exit2(self):
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "野量差\tdrift\t1\t项\t100\t100\t挂靠失败\n"
                   "防水\tforced\t1\t项\t100\t100\t-\n"
                   "搬运\tpadded\t1\t项\t100\t100\t-\n")
        code, out = run(["validate", self.quote, self.addons])
        self.assertEqual(code, 2)

    def test_pct_absurd_flagged(self):
        # 管理费记成 60% 合同额 → 比例荒谬
        self.write(self.quote,
                   "item\tqty\tunit\tunit_price\tamount\test\tnote\n"
                   "水电\t100\tm\t50\t5000\tfixed\t-\n"
                   "瓦工\t100\t㎡\t60\t6000\tfixed\t-\n"
                   "管理费\t1\t项\t50000\t50000\tfixed\t比例荒谬\n")
        self.write(self.addons,
                   "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n"
                   "防水\tforced\t1\t项\t100\t100\t-\n"
                   "搬运\tpadded\t1\t项\t100\t100\t-\n"
                   "税金\tpadded\t1\t项\t100\t100\t-\n")
        code, out = run(["validate", self.quote, self.addons])
        self.assertEqual(code, 2)
        self.assertIn("比例荒谬", out)

    def test_empty_addons_ok(self):
        self.write(self.addons, "item\tkind\tqty\tunit\tunit_price\tamount\tnote\n")
        code, out = run(["validate", self.quote, self.addons])
        self.assertEqual(code, 0)


# --------------------------------------------------------------- 常量与快照
class Constants(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual((lowball.EXIT_OK, lowball.EXIT_RISKY, lowball.EXIT_BROKEN,
                          lowball.EXIT_THIN, lowball.EXIT_RED), (0, 1, 2, 3, 4))

    def test_default_baselines_shape(self):
        uni = [b for b in lowball.DEFAULT_BASELINES if b[5] == "universal"]
        con = [b for b in lowball.DEFAULT_BASELINES if b[5] == "conditional"]
        self.assertGreaterEqual(len(uni), 4)
        self.assertGreaterEqual(len(con), 6)
        for k, a, lo, hi, u, c, t in lowball.DEFAULT_BASELINES:
            self.assertLessEqual(lo, hi)
            self.assertTrue(a and u and k)

    def test_display_width(self):
        self.assertEqual(lowball.dw("abc"), 3)
        self.assertEqual(lowball.dw("防水"), 4)
        self.assertEqual(lowball.pad("ab", 4), "ab  ")
        self.assertEqual(lowball.pad("ab", 4, right=True), "  ab")


class Snapshots(unittest.TestCase):
    """示例输出逐字节可复现(不依赖当前时间)。"""

    def test_snapshots_reproduce(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = subprocess.run(
                [sys.executable, os.path.join(EXAMPLES, "build_examples.py"), "--check"],
                capture_output=True, text=True)
        self.assertEqual(rc.returncode, 0,
                         f"快照字节校验失败:\n{rc.stdout}\n{rc.stderr}")

    def test_nine_snapshots_exist(self):
        snaps = [f for f in os.listdir(EXAMPLES) if f.startswith("sample-")]
        self.assertEqual(len(snaps), 9)

    def test_snapshot_exit_codes_match_design(self):
        design = {
            "sample-audit.txt": "红线 ✗ exit 4",
            "sample-gaps.txt": "红线 ✗ exit 4",
            "sample-judge.txt": "裁决 ✗ 不签",
            "sample-judge-good.txt": "裁决 ✓ 可以谈",
            "sample-gaps-good.txt": "常识清单覆盖完整",
            "sample-prices.txt": "红线 ✗ exit 4",
            "sample-sign-kill.txt": "✗ 越线",
            "sample-sign-ok.txt": "✓ 过闸",
            "sample-validate.txt": "全部通过",
        }
        for fname, marker in design.items():
            with open(os.path.join(EXAMPLES, fname), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn(marker, text, fname)


if __name__ == "__main__":
    unittest.main()
