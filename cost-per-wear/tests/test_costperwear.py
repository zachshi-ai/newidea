#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for cost-per-wear (每穿成本).

验收标准全部转成自动化测试：
  ParseTests     衣柜清单解析：列名别名/日期/季节/坏行/编码
  CpwTests       每穿成本数学：0 次 = 未定型（None）
  GraveyardTests 坟场规则：180 天豁免期、长眠线、沉睡资金不重复计
  BoardTests     排行榜：真实价格降序、便宜货升序、只收穿过的
  HoardTests     堆积区：阈值、投入合计
  CoverageTests  品类×季节覆盖矩阵：all 归四季
  PlanTests      剁手模拟器：堆积否决 / 孤儿否决 / 填补缺口 / --want 解析
  ScenarioTests  wardrobe.csv ground truth 精确恢复
  CliTests       audit/plan/validate + 退出码 0/2/3/4 + --today 可复现
  SyncTests      样例可从零重建且逐字节一致
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cost_per_wear as cw  # noqa: E402

EXAMPLES = ROOT / "examples"
TODAY = date(2026, 9, 4)   # 与 examples 钉死同一天


def write_csv(tmp, text, encoding="utf-8", name="wardrobe.csv"):
    p = Path(tmp) / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return p


def read_items(tmp, text, **kw):
    return cw.read_wardrobe(write_csv(tmp, text, **kw))


def audit_csv(tmp, text, **kw):
    return cw.audit(read_items(tmp, text), today=kw.pop("today", TODAY), **kw)


HEADER = "名称,类别,季节,价格,购买日期,穿着次数,上次穿\n"


# ---------------------------------------------------------------------------
# 解析

class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_basic(self):
        w = read_items(self.tmp, HEADER + "白T A,白T,all,79,2024-03-01,24,2026-08-30\n")
        it = w["items"][0]
        self.assertEqual(it["name"], "白T A")
        self.assertEqual(it["cat"], "白t")
        self.assertEqual(it["price"], 79.0)
        self.assertEqual(it["wears"], 24)
        self.assertEqual(it["seasons"], "ALL")

    def test_season_multi_and_aliases(self):
        w = read_items(self.tmp, HEADER +
                       "风衣,外套,春秋,1200,2023-10-01,96,\n"
                       "羽绒服,羽绒服,winter,1599,2025-06-01,0,\n")
        self.assertEqual(w["items"][0]["seasons"], {"春", "秋"})
        self.assertEqual(w["items"][1]["seasons"], {"冬"})

    def test_english_headers(self):
        w = read_items(self.tmp,
                       "item,category,season,price,acquired,wears,last_worn\n"
                       "coat,外套,all,1200,2023-10-01,96,2026-08-25\n")
        self.assertEqual(w["items"][0]["price"], 1200.0)

    def test_gbk(self):
        w = read_items(self.tmp, HEADER + "白T A,白T,all,79,,24,\n", encoding="gbk")
        self.assertEqual(w["items"][0]["name"], "白T A")

    def test_optional_columns_missing(self):
        w = read_items(self.tmp, "名称,类别,价格,穿着次数\n白T A,白T,79,24\n")
        it = w["items"][0]
        self.assertIsNone(it["acquired"])
        self.assertEqual(it["seasons"], "ALL")

    def test_bad_rows_skipped(self):
        text = (HEADER +
                ",白T,all,79,,24,\n"          # 无名称
                "白T B,白T,all,abc,,24,\n"    # 价格坏
                "白T C,白T,all,79,,x,\n"      # 次数坏
                "白T D,白T,all,-1,,24,\n"     # 负价
                "白T E,白T,all,79,,24,\n")
        w = read_items(self.tmp, text)
        self.assertEqual(len(w["items"]), 1)
        self.assertEqual(w["skipped"], 4)

    def test_missing_columns_error(self):
        with self.assertRaises(cw.WardrobeError):
            read_items(self.tmp, "名称,价格\n白T A,79\n")

    def test_missing_file_error(self):
        with self.assertRaises(cw.WardrobeError):
            cw.read_wardrobe("no/such/file.csv")

    def test_date_formats(self):
        w = read_items(self.tmp, HEADER +
                       "A,白T,all,79,2024/3/1,24,\n"
                       "B,白T,all,79,2024.03.02,24,\n"
                       "C,白T,all,79,20240303 10:00,24,\n")
        self.assertEqual([i["acquired"] for i in w["items"]],
                         [date(2024, 3, 1), date(2024, 3, 2), date(2024, 3, 3)])


# ---------------------------------------------------------------------------
# CPW 数学

class CpwTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(cw.cpw(1200.0, 96), 12.5)

    def test_zero_wears_undefined(self):
        self.assertIsNone(cw.cpw(1599.0, 0))

    def test_rounding(self):
        self.assertEqual(cw.cpw(79.0, 3), 26.33)


# ---------------------------------------------------------------------------
# 坟场

class GraveyardTests(unittest.TestCase):
    def never_worn_names(self, rep):
        return {r["name"] for r in rep["graveyard"]["never_worn"]}

    def test_orphan_after_grace_period(self):
        text = (HEADER +
                "旧衣,白T,all,79,2026-01-10,0,\n"    # 237d
                "新衣,衬衫,all,249,2026-05-27,0,\n")  # 100d 豁免
        rep = audit_csv(self.tmp, text)
        self.assertEqual(self.never_worn_names(rep), {"旧衣"})

    def test_no_acquired_date_counts_as_orphan(self):
        rep = audit_csv(self.tmp, HEADER + "来历不明,白T,all,79,,0,\n")
        self.assertEqual(self.never_worn_names(rep), {"来历不明"})

    def test_orphan_days_configurable(self):
        text = HEADER + "旧衣,白T,all,79,2026-05-27,0,\n"  # 100d
        rep = audit_csv(self.tmp, text, orphan_days=90)
        self.assertEqual(self.never_worn_names(rep), {"旧衣"})

    def test_asleep_rule(self):
        text = (HEADER +
                "长眠,衬衫,all,699,2023-05-01,1,2025-06-01\n"   # 461d
                "还活着,衬衫,all,99,2024-01-01,5,2026-01-20\n")  # 227d
        rep = audit_csv(self.tmp, text)
        self.assertEqual({r["name"] for r in rep["graveyard"]["asleep"]}, {"长眠"})

    def test_sleeping_capital_no_double_count(self):
        # 从未穿 + 上次穿很久以前（矛盾数据）只计一次
        text = HEADER + "矛盾体,衬衫,all,699,2023-05-01,0,2025-06-01\n"
        rep = audit_csv(self.tmp, text)
        self.assertEqual(rep["graveyard"]["sleeping_capital"], 699.0)

    def test_share_math(self):
        text = (HEADER +
                "吃灰,白T,all,100,2026-01-10,0,\n"
                "常穿,外套,all,300,2024-01-01,100,2026-08-30\n")
        rep = audit_csv(self.tmp, text)
        self.assertEqual(rep["graveyard"]["share"], 0.25)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# 排行榜

class BoardTests(unittest.TestCase):
    def test_cpw_board_desc_and_worn_only(self):
        text = (HEADER +
                "常穿,外套,all,1200,2023-10-01,96,\n"
                "穿过一次,衬衫,all,699,2023-05-01,1,\n"
                "吃灰,白T,all,79,2026-01-10,0,\n")
        rep = audit_csv(self.tmp, text)
        names = [r["name"] for r in rep["cpw_board"]]
        self.assertEqual(names, ["穿过一次", "常穿"])
        self.assertEqual(rep["cpw_board"][0]["cpw"], 699.0)

    def test_value_board_asc(self):
        text = (HEADER +
                "拖鞋,鞋,all,39,2025-12-01,60,\n"
                "白T,白T,all,79,2024-03-01,24,\n")
        rep = audit_csv(self.tmp, text)
        self.assertEqual([r["name"] for r in rep["value_board"]], ["拖鞋", "白T"])

    def test_board_capped_at_15(self):
        rows = "".join(f"单品{i},类别{i % 20},all,{100 + i},2024-01-01,{i + 1},\n"
                       for i in range(20))
        rep = audit_csv(self.tmp, HEADER + rows)
        self.assertEqual(len(rep["cpw_board"]), 15)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# 堆积区与覆盖矩阵

class HoardTests(unittest.TestCase):
    def test_threshold_and_spend(self):
        text = HEADER + "".join(f"白T{i},白T,all,79,2024-01-01,{i + 1},\n"
                                for i in range(4))
        rep = audit_csv(self.tmp, text)
        self.assertEqual(rep["hoarded"][0]["count"], 4)
        self.assertEqual(rep["hoarded"][0]["spend"], 316.0)

    def test_below_threshold_excluded(self):
        text = HEADER + "".join(f"白T{i},白T,all,79,2024-01-01,{i + 1},\n"
                                for i in range(3))
        rep = audit_csv(self.tmp, text)
        self.assertEqual(rep["hoarded"], [])

    def test_dup_threshold_configurable(self):
        text = HEADER + "".join(f"白T{i},白T,all,79,2024-01-01,{i + 1},\n"
                                for i in range(3))
        rep = audit_csv(self.tmp, text, dup_threshold=3)
        self.assertEqual(rep["hoarded"][0]["count"], 3)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()


class CoverageTests(unittest.TestCase):
    def test_all_counts_toward_four_seasons(self):
        rep = audit_csv(self.tmp, HEADER +
                        "A,白T,all,79,2024-01-01,1,\n"
                        "B,羽绒服,冬,1599,2025-06-01,0,\n")
        self.assertEqual(rep["coverage"]["白t"], {"春": 1, "夏": 1, "秋": 1, "冬": 1})
        self.assertEqual(rep["coverage"]["羽绒服"], {"春": 0, "夏": 0, "秋": 0, "冬": 1})

    def test_multi_season(self):
        rep = audit_csv(self.tmp, HEADER + "风衣,外套,春秋,1200,2023-10-01,96,\n")
        self.assertEqual(rep["coverage"]["外套"], {"春": 1, "夏": 0, "秋": 1, "冬": 0})

    def setUp(self):
        self.tmp = tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# 剁手模拟器

class PlanTests(unittest.TestCase):
    WARDROBE = (HEADER +
                "白T A,白T,all,79,2024-03-01,24,\n"
                "白T B,白T,all,79,2024-06-15,18,\n"
                "白T C,白T,all,79,2025-01-20,12,\n"
                "白T D,白T,all,79,2025-05-05,8,\n"
                "白T G,白T,all,79,2026-01-10,0,\n"      # 孤儿 + 堆积
                "风衣,外套,all,1200,2023-10-01,96,\n"
                "羽绒服,羽绒服,冬,1599,2025-06-01,0,\n")  # 孤儿，品类仅 1 件

    def plan(self, want, **kw):
        w = cw.read_wardrobe(write_csv(self.tmp, self.WARDROBE))
        return cw.plan(w, cw.parse_want(want), today=TODAY, **kw)

    def test_hoard_rejected(self):
        v = self.plan("白T:79")[0]
        self.assertEqual(v["verdict"], "REJECT")
        self.assertIn("第 6 件", v["reason"])

    def test_orphan_veto_even_when_category_small(self):
        v = self.plan("羽绒服:1299")[0]
        self.assertEqual(v["verdict"], "REJECT")
        self.assertIn("从未穿过", v["reason"])
        self.assertIn("羽绒服", v["reason"])

    def test_fill_gap_accepted(self):
        self.assertEqual(self.plan("外套:899")[0]["verdict"], "ACCEPT")
        v = self.plan("冬靴:599")[0]
        self.assertEqual(v["verdict"], "ACCEPT")
        self.assertIn("0 件", v["reason"])

    def test_orphan_younger_than_grace_does_not_veto(self):
        text = (HEADER +
                "新卫衣,卫衣,all,249,2026-05-27,0,\n")
        w = cw.read_wardrobe(write_csv(self.tmp, text))
        v = cw.plan(w, cw.parse_want("卫衣:199"), today=TODAY)
        self.assertEqual(v[0]["verdict"], "ACCEPT")

    def test_parse_want(self):
        wants = cw.parse_want("外套:899，白T：79")
        self.assertEqual(wants, [("外套", 899.0), ("白T", 79.0)])
        with self.assertRaises(cw.WardrobeError):
            cw.parse_want("外套899")
        with self.assertRaises(cw.WardrobeError):
            cw.parse_want("外套:abc")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# ground truth

class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = cw.read_wardrobe(EXAMPLES / "wardrobe.csv")
        cls.rep = cw.audit(cls.w, today=TODAY)
        wants = cw.parse_want("外套:899,白T:79,羽绒服:1299,冬靴:599")
        cls.plan_v = cw.plan(cls.w, wants, today=TODAY)

    def test_shape(self):
        self.assertEqual(self.rep["window"]["items"], 32)
        self.assertEqual(self.rep["window"]["skipped"], 0)
        self.assertEqual(self.rep["window"]["total_spend"], 9215.0)

    def test_sleeping_capital_and_share(self):
        g = self.rep["graveyard"]
        self.assertEqual(g["sleeping_capital"], 4572.0)
        self.assertEqual(g["share"], 0.4961)
        self.assertEqual({r["name"] for r in g["never_worn"]},
                         {"白T 基础款G", "羽绒服 打折购入", "连衣裙 碎花", "连衣裙 小礼裙"})
        self.assertEqual({r["name"] for r in g["asleep"]},
                         {"婚礼衬衫", "跑鞋 缓震", "连衣裙 波点", "连衣裙 素色"})

    def test_grace_period_items_not_in_graveyard(self):
        names = ({r["name"] for r in self.rep["graveyard"]["never_worn"]} |
                 {r["name"] for r in self.rep["graveyard"]["asleep"]})
        self.assertNotIn("卫衣 灰色", names)   # 100d 豁免
        self.assertNotIn("船袜", names)        # 95d 豁免

    def test_hoarded_categories(self):
        self.assertEqual([(h["category"], h["count"]) for h in self.rep["hoarded"]],
                         [("白T", 7), ("袜子", 6), ("连衣裙", 4)])

    def test_cpw_board_top(self):
        top = self.rep["cpw_board"][0]
        self.assertEqual(top["name"], "婚礼衬衫")
        self.assertEqual(top["cpw"], 699.0)

    def test_value_board_top(self):
        self.assertEqual(self.rep["value_board"][0]["name"], "白袜A")

    def test_coverage_matrix(self):
        self.assertEqual(self.rep["coverage"]["白t"],
                         {"春": 7, "夏": 7, "秋": 7, "冬": 7})
        self.assertEqual(self.rep["coverage"]["羽绒服"]["冬"], 1)
        self.assertEqual(self.rep["coverage"]["羽绒服"]["夏"], 0)

    def test_plan_verdicts(self):
        by_want = {v["want"]: v for v in self.plan_v}
        self.assertEqual(by_want["外套"]["verdict"], "ACCEPT")
        self.assertEqual(by_want["冬靴"]["verdict"], "ACCEPT")
        self.assertEqual(by_want["白T"]["verdict"], "REJECT")
        self.assertIn("第 8 件", by_want["白T"]["reason"])
        self.assertEqual(by_want["羽绒服"]["verdict"], "REJECT")
        self.assertIn("从未穿过", by_want["羽绒服"]["reason"])


# ---------------------------------------------------------------------------
# CLI

class CliTests(unittest.TestCase):
    CSV = str(EXAMPLES / "wardrobe.csv")
    TODAY = ["--today", "2026-09-04"]

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(ROOT / "cost_per_wear.py"), *argv],
            capture_output=True, text=True,
        )

    def test_audit_text_and_json(self):
        r = self.run_cli("audit", self.CSV, *self.TODAY)
        self.assertEqual(r.returncode, 0)
        self.assertIn("沉睡资金 4572.00", r.stdout)
        j = json.loads(self.run_cli("audit", self.CSV, "--format", "json",
                                    *self.TODAY).stdout)
        self.assertEqual(j["window"]["items"], 32)
        self.assertEqual(j["graveyard"]["sleeping_capital"], 4572.0)

    def test_today_changes_verdict(self):
        # 把今天拨回 2025-09-01：4 件孤儿要么尚未购买、要么仍在豁免期内
        r = self.run_cli("audit", self.CSV, "--today", "2025-09-01",
                         "--format", "json")
        j = json.loads(r.stdout)
        self.assertEqual(j["graveyard"]["never_worn"], [])
        self.assertEqual(j["graveyard"]["asleep"], [])
        self.assertEqual(j["window"]["today"], "2025-09-01")

    def test_plan_and_strict_gate(self):
        want = "--want", "外套:899,白T:79"
        self.assertEqual(self.run_cli("plan", self.CSV, *want, *self.TODAY).returncode, 0)
        self.assertEqual(
            self.run_cli("plan", self.CSV, *want, "--strict", *self.TODAY).returncode, 4)
        j = json.loads(self.run_cli("plan", self.CSV, *want, "--format", "json",
                                    *self.TODAY).stdout)
        self.assertEqual(len(j["plan"]), 2)

    def test_validate(self):
        r = self.run_cli("validate", self.CSV)
        self.assertEqual(r.returncode, 0)
        self.assertIn("ok: 32 items", r.stdout)

    def test_orphan_alert_gate(self):
        self.assertEqual(
            self.run_cli("audit", self.CSV, "--orphan-alert", "0.25", *self.TODAY).returncode, 4)
        self.assertEqual(
            self.run_cli("audit", self.CSV, "--orphan-alert", "0.6", *self.TODAY).returncode, 0)

    def test_missing_file_exit_3(self):
        self.assertEqual(self.run_cli("audit", "no/such.csv").returncode, 3)

    def test_unparseable_csv_exit_3(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = write_csv(tmp, "foo,bar\n1,2\n", name="bad.csv")
            self.assertEqual(self.run_cli("audit", str(p)).returncode, 3)

    def test_bad_want_exit_3(self):
        self.assertEqual(self.run_cli("plan", self.CSV, "--want", "外套899",
                                      *self.TODAY).returncode, 3)

    def test_no_subcommand_exit_2(self):
        self.assertEqual(self.run_cli().returncode, 2)


# ---------------------------------------------------------------------------
# 样例可复现

class SyncTests(unittest.TestCase):
    def test_examples_rebuild_byte_identical(self):
        subprocess.run([sys.executable, str(EXAMPLES / "build_examples.py")],
                       check=True, capture_output=True)
        audit = subprocess.run(
            [sys.executable, str(ROOT / "cost_per_wear.py"), "audit",
             str(EXAMPLES / "wardrobe.csv"), "--today", "2026-09-04"],
            capture_output=True, text=True, check=True)
        plan_out = subprocess.run(
            [sys.executable, str(ROOT / "cost_per_wear.py"), "plan",
             str(EXAMPLES / "wardrobe.csv"),
             "--want", "外套:899,白T:79,羽绒服:1299,冬靴:599", "--today", "2026-09-04"],
            capture_output=True, text=True, check=True)
        self.assertEqual((EXAMPLES / "sample-audit.txt").read_text(encoding="utf-8"),
                         audit.stdout)
        self.assertEqual((EXAMPLES / "sample-plan.txt").read_text(encoding="utf-8"),
                         plan_out.stdout)


if __name__ == "__main__":
    unittest.main()
