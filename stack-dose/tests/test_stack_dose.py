# -*- coding: utf-8 -*-
"""stack-dose · 叠方 验收测试.

验收标准(README 承诺的全部转成自动化测试):
  解析层    中英列名同效/药名归一/成分别 名归一/未知药/坏日期/坏时间/
            非正数量/重复行/自定义药表整药替换/坏药表/缺文件
  聚合层    单药成分拆解/Σ逐行==Σ按日聚合/展开恒等式/as-of 剪切(含边界)/
            缺省自锚账本末日/乱序载入重排
  判级层    恰线不亮(单药说明书满频次不冤枉)/越一线 STACKED/越药典
            OVERDOSE 恰 4000 仍 STACKED/无先验 n/a 只发表/--soft/--hard/
            --gap 翻案
  report    样例账本 D1 全绿 exit 0/D2 STACKED/D4 OVERDOSE/时间机器回放/
            空账 exit 3/全剪 exit 3
  interval  3h CROWDED/恰 4h 不亮/3h59m 亮/跨日累计/成分过滤/无先验不审/
            查无成分如实说
  combo     共享成分点名/无共享不冤枉(新康泰克+美林 OK)/times 外推越线/
            未知药/坏 times
  share     反向索引计数/--ingredient/查无成分如实说
  validate  恒等式全绿/账坏 exit 2
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stack_dose  # noqa: E402

from decimal import Decimal as D  # noqa: E402


def run(argv):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = stack_dose.main(argv)
    return code, buf.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tsv(self, name, content):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    # 小陈感冒周:01-05 OK / 01-06 STACKED(2540) / 01-07 CROWDED(3h)
    #           / 01-08 OVERDOSE(4405) / 01-09 自定义药康复 OK
    LEDGER = """date\ttime\tdrug\tqty\tnote
2026-01-05\t08:00\t泰诺\t1\t感冒第一天
2026-01-05\t13:00\t999感冒灵\t2\t
2026-01-05\t21:30\t白加黑夜片\t1\t睡个好觉
2026-01-06\t08:00\t泰诺\t1\t
2026-01-06\t12:30\t999感冒灵\t2\t
2026-01-06\t15:00\t维C银翘片\t3\t
2026-01-06\t19:00\t泰诺林\t2\t烧起来了
2026-01-06\t22:00\t散利痛\t2\t
2026-01-07\t08:00\t泰诺林\t1\t
2026-01-07\t11:00\t泰诺\t1\t才隔三小时
2026-01-07\t20:00\t999感冒灵\t2\t
2026-01-08\t07:30\t泰诺林\t2\t高烧不退全家投喂
2026-01-08\t10:00\t散利痛\t4\t
2026-01-08\t13:00\t999感冒灵\t4\t
2026-01-08\t16:00\t维C银翘片\t6\t
2026-01-08\t19:30\t泰诺\t2\t
2026-01-08\t22:30\t白加黑夜片\t1\t
2026-01-09\t09:00\t诊所白瓶药\t2\t去医院开了药
2026-01-09\t21:00\t999感冒灵\t1\t
"""
    CUSTOM_MEDS = """name\tingredient\tmg\tunit
诊所白瓶药\t对乙酰氨基酚\t300\t片
"""


class TestParse(Base):
    def test_load_counts(self):
        p = self.tsv("d.tsv", self.LEDGER)
        m = stack_dose.Meds()
        m.merge_file(self.tsv("m.tsv", self.CUSTOM_MEDS))
        doses = stack_dose.load_doses(p, m)
        self.assertEqual(len(doses), 19)

    def test_cn_columns(self):
        p = self.tsv("d.tsv", "日期\t时间\t药品\t数量\t备注\n"
                              "2026-01-05\t08:00\t泰诺\t1\t\n")
        m = stack_dose.Meds()
        doses = stack_dose.load_doses(p, m)
        self.assertEqual(len(doses), 1)
        self.assertEqual(doses[0].drug, "泰诺")

    def test_drug_name_normalized(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰 诺\t1\n"
                              "2026-01-05\t12:00\tTYLENOL\t1\n")
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰 诺\t1\n")
        m = stack_dose.Meds()
        doses = stack_dose.load_doses(p, m)
        self.assertEqual(doses[0].drug, "泰诺")  # 展示名归到药表名

    def test_unknown_drug(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t神仙水\t1\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("未知药名", err)

    def test_bad_date(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-1-5\t08:00\t泰诺\t1\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("坏日期", err)

    def test_bad_time(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t24:00\t泰诺\t1\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("坏时间", err)

    def test_nonpositive_qty(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺\t0\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("必须为正", err)

    def test_fractional_qty(self):
        # 美林混悬液 20 mg/ml × 7.5 ml = 150 mg——小数是剂型的日常
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t美林\t7.5\t\n")
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertIn("150", out)

    def test_duplicate_row(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺\t1\n"
                              "2026-01-05\t08:00\t泰诺\t1\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 2)
        self.assertIn("重复服药行", err)

    def test_missing_file(self):
        code, _, err = run(["report", os.path.join(self.tmp, "nope.tsv")])
        self.assertEqual(code, 2)
        self.assertIn("不存在", err)

    def test_custom_meds_merge_and_replace(self):
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        p = self.tsv("d.tsv", self.LEDGER)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-09"])
        self.assertEqual(code, 4)
        self.assertIn("自定义 1", out)
        self.assertIn("诊所白瓶药", out)

    def test_custom_meds_replaces_builtin(self):
        # 同名药整药替换:自定义「泰诺」只含咖啡因,酚不再被计入
        mp = self.tsv("m.tsv", "name\tingredient\tmg\tunit\n"
                               "泰诺\t咖啡因\t60\t片\n")
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺\t1\n")
        code, out, _ = run(["report", p, "--meds", mp])
        self.assertEqual(code, 0)
        self.assertNotIn("对乙酰氨基酚", out.split("─")[0])
        self.assertIn("咖啡因", out)

    def test_bad_meds_row(self):
        mp = self.tsv("m.tsv", "name\tingredient\tmg\tunit\n"
                               "假药\t对乙酰氨基酚\t0\t片\n")
        p = self.tsv("d.tsv", self.LEDGER)
        code, _, err = run(["report", p, "--meds", mp])
        self.assertEqual(code, 2)
        self.assertIn("必须为正", err)

    def test_ing_alias(self):
        self.assertEqual(stack_dose.norm_ing("扑热息痛"), "对乙酰氨基酚")
        self.assertEqual(stack_dose.norm_ing("Paracetamol"), "对乙酰氨基酚")
        self.assertEqual(stack_dose.norm_ing("马来酸氯苯那敏"), "氯苯那敏")


class TestAggregate(Base):
    def test_single_dose_expansion(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺\t1\n")
        m = stack_dose.Meds()
        events = stack_dose.expand(stack_dose.load_doses(p, m), m)
        self.assertEqual(len(events), 4)  # 泰诺 4 成分
        by_ing = {ing: amt for _, ing, amt, _ in events}
        self.assertEqual(by_ing["对乙酰氨基酚"], D("325"))
        self.assertEqual(by_ing["氯苯那敏"], D("2"))

    def test_line_sum_equals_day_sum(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        m = stack_dose.Meds()
        m.merge_file(mp)
        doses = stack_dose.load_doses(p, m)
        events = stack_dose.expand(doses, m)
        days = stack_dose.day_totals(events)
        line_sum = sum((a for _, _, a, _ in events), D(0))
        day_sum = sum((t for ings in days.values() for t in ings.values()), D(0))
        self.assertEqual(line_sum, day_sum)

    def test_expansion_identity(self):
        p = self.tsv("d.tsv", self.LEDGER)
        m = stack_dose.Meds()
        m.merge_file(self.tsv("m.tsv", self.CUSTOM_MEDS))
        doses = stack_dose.load_doses(p, m)
        events = stack_dose.expand(doses, m)
        n_ing = sum(len(rows) for _, rows in
                    (m.get(d.drug_raw) for d in doses))
        self.assertEqual(n_ing, len(events))

    def test_asof_clips_inclusive(self):
        p = self.tsv("d.tsv", self.LEDGER)
        m = stack_dose.Meds()
        m.merge_file(self.tsv("m.tsv", self.CUSTOM_MEDS))
        doses = stack_dose.load_doses(p, m)
        clipped = stack_dose.clip(doses, stack_dose.dt.date(2026, 1, 6))
        self.assertEqual(max(d.date for d in clipped).day, 6)
        self.assertTrue(all(d.date <= stack_dose.dt.date(2026, 1, 6)
                            for d in clipped))

    def test_default_asof_is_ledger_max(self):
        p = self.tsv("d.tsv", self.LEDGER)
        code, out, _ = run(["report", p, "--meds",
                            self.tsv("m.tsv", self.CUSTOM_MEDS)])
        self.assertIn("账本末日)", out)
        self.assertIn("2026-01-09", out)

    def test_out_of_order_sorted(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-06\t08:00\t泰诺\t1\n"
                              "2026-01-05\t21:00\t泰诺\t1\n"
                              "2026-01-05\t08:00\t泰诺\t1\n")
        m = stack_dose.Meds()
        doses = stack_dose.load_doses(p, m)
        self.assertEqual([d.date.day for d in doses], [5, 5, 6])
        self.assertEqual([d.mins for d in doses[:2]], [8 * 60, 21 * 60])


class TestJudge(unittest.TestCase):
    def test_exact_soft_is_ok(self):
        # 单药按说明书满频次:酚 500×4 = 2000 恰线不亮——判级线画在这里的意义
        self.assertEqual(stack_dose.judge(D("2000"), (2000, 4000)), "OK")

    def test_just_over_soft(self):
        self.assertEqual(stack_dose.judge(D("2000.01"), (2000, 4000)), "STACKED")

    def test_hard_priority(self):
        self.assertEqual(stack_dose.judge(D("4000.01"), (2000, 4000)), "OVERDOSE")

    def test_exact_hard_is_stacked(self):
        # 恰 4000 = 叠满线但未越线:STACKED,判级恰线语义钉死
        self.assertEqual(stack_dose.judge(D("4000"), (2000, 4000)), "STACKED")

    def test_no_prior_is_na(self):
        self.assertEqual(stack_dose.judge(D("90"), (None, None)), "NA")

    def test_soft_only(self):
        self.assertEqual(stack_dose.judge(D("500"), (400, None)), "STACKED")


class TestReport(Base):
    def test_d1_all_green(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-05"])
        self.assertEqual(code, 0)
        self.assertIn("判定 OK", out)
        self.assertIn("1,050", out)  # 325 + 200×2 + 325

    def test_d2_stacked(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-06"])
        self.assertEqual(code, 4)
        self.assertIn("判定 STACKED", out)
        self.assertIn("2,540", out)  # 325+400+315+1000+500
        self.assertIn("藏在当日 5 种药里", out)

    def test_d3_crowded(self):
        # 窗口里 D2 的 STACKED 仍是全局最重;D3 自己的灯是 CROWDED
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-07"])
        self.assertEqual(code, 4)
        self.assertIn("判定 STACKED", out)
        self.assertIn("▸ 2026-01-07 周三   🔴 CROWDED", out)
        self.assertIn("01-07 08:00 泰诺林 → 01-07 11:00 泰诺", out)
        self.assertIn("间隔 180 分钟 < 240(q4h)", out)

    def test_crowded_only_ledger(self):
        # 只有间隔违规、没有越线的账本:判定 CROWDED——间隔也是叠加
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\tnote\n"
                              "2026-01-05\t08:00\t泰诺林\t1\t\n"
                              "2026-01-05\t11:00\t泰诺\t1\t\n")
        code, out, _ = run(["report", p])
        self.assertEqual(code, 4)
        self.assertIn("判定 CROWDED", out)

    def test_d4_overdose(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-08"])
        self.assertEqual(code, 4)
        self.assertIn("判定 OVERDOSE", out)
        self.assertIn("4,405", out)  # 1000+1000+800+630+650+325

    def test_full_ledger_worst_is_overdose(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp])
        self.assertEqual(code, 4)
        self.assertIn("判定 OVERDOSE", out)
        self.assertIn("1 OVERDOSE · 1 STACKED · 1 CROWDED · 2 OK", out)
        self.assertIn("判定 OVERDOSE", out)

    def test_time_machine(self):
        # 钉回第一天:当时全绿——as-of 是时间机器不是错误过滤器
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-05"])
        self.assertEqual(code, 0)
        self.assertIn("显式钉死", out)

    def test_empty_ledger_refuses(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n")
        code, _, err = run(["report", p])
        self.assertEqual(code, 3)
        self.assertIn("拒绝", err)

    def test_asof_clips_everything_refuses(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, _, err = run(["report", p, "--meds", mp, "--as-of", "2025-01-01"])
        self.assertEqual(code, 3)

    def test_na_published_not_judged(self):
        # 自定义无先验成分:只发表不判级;伪麻黄碱(内置无上限先验)同此
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t新康泰克\t1\n")
        code, out, _ = run(["report", p])
        self.assertEqual(code, 0)
        self.assertIn("无先验上限", out)
        self.assertIn("n/a", out)

    def test_soft_flag_overrides(self):
        # --soft 把酚的保守线压到 1000:同样的账,线一动灯就动——先验是旗标
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-05",
                            "--soft", "对乙酰氨基酚=1000"])
        self.assertEqual(code, 4)
        self.assertIn("STACKED", out)

    def test_hard_flag_overrides(self):
        # hard 压到 2000:昨日 2,540 从 STACKED 升格 OVERDOSE——线的形状你说了算
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-06",
                            "--hard", "对乙酰氨基酚=2000"])
        self.assertEqual(code, 4)
        self.assertIn("判定 OVERDOSE", out)

    def test_gap_flag_overrides(self):
        # 间隔闸翻案:q4h 放宽到 120 分钟,180 分钟的段不再违规;
        # 但 D2 的 STACKED 与线有关,与间隔无关——各闸各管各的案
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["report", p, "--meds", mp, "--as-of", "2026-01-07",
                            "--gap", "对乙酰氨基酚=120"])
        self.assertEqual(code, 4)
        self.assertNotIn("间隔 180 分钟", out)

    def test_no_prior_can_be_taught(self):
        # 伪麻黄碱无先验;--soft 教会它之后判级生效
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t新康泰克\t1\n"
                              "2026-01-05\t09:00\t新康泰克\t1\n")
        code, out, _ = run(["report", p, "--soft", "伪麻黄碱=150"])
        self.assertEqual(code, 4)
        self.assertIn("180", out)


class TestInterval(Base):
    def setUp(self):
        super().setUp()
        self.p = self.tsv("d.tsv", self.LEDGER)
        self.mp = self.tsv("m.tsv", self.CUSTOM_MEDS)

    def test_crowded_3h(self):
        code, out, _ = run(["interval", self.p, "--meds", self.mp,
                            "--as-of", "2026-01-07"])
        self.assertEqual(code, 4)
        self.assertIn("判定 CROWDED", out)
        self.assertIn("01-07 08:00 泰诺林 → 01-07 11:00 泰诺", out)
        self.assertIn("180 分钟", out)

    def test_exact_gap_ok(self):
        # 恰 4h:08:00 与 12:00——线上不亮
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺林\t1\n"
                              "2026-01-05\t12:00\t泰诺\t1\n")
        code, out, _ = run(["interval", p])
        self.assertEqual(code, 0)
        self.assertIn("判定 OK", out)

    def test_3h59m_crowded(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t08:00\t泰诺林\t1\n"
                              "2026-01-05\t11:59\t泰诺\t1\n")
        code, out, _ = run(["interval", p])
        self.assertEqual(code, 4)
        self.assertIn("239 分钟", out)

    def test_cross_day_gap(self):
        # 23:00 → 次日 06:00 = 7h:跨日是间隔的一部分,不是新的一天重新开始
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n"
                              "2026-01-05\t23:00\t泰诺林\t1\n"
                              "2026-01-06\t06:00\t泰诺\t1\n")
        code, out, _ = run(["interval", p])
        self.assertEqual(code, 0)

    def test_ingredient_filter(self):
        code, out, _ = run(["interval", self.p, "--meds", self.mp,
                            "--as-of", "2026-01-07",
                            "--ingredient", "布洛芬"])
        self.assertEqual(code, 0)
        self.assertIn("没有含 布洛芬 的服药事件", out)

    def test_no_prior_not_audited(self):
        # 氯苯那敏无间隔先验:不审,不装懂
        code, out, _ = run(["interval", self.p, "--meds", self.mp,
                            "--as-of", "2026-01-07",
                            "--ingredient", "氯苯那敏"])
        self.assertIn("无最短间隔先验", out)

    def test_empty_ledger(self):
        p = self.tsv("d.tsv", "date\ttime\tdrug\tqty\n")
        code, _, err = run(["interval", p])
        self.assertEqual(code, 3)


class TestCombo(unittest.TestCase):
    def test_shared_ingredient_named(self):
        # 630×3 = 1,890 < 2,000:共享成分点名,但按 3 次/日恰不越线
        code, out, _ = run(["combo", "--drugs", "泰诺,999感冒灵,维C银翘片"])
        self.assertEqual(code, 0)
        self.assertIn("共享成分: 对乙酰氨基酚", out)
        self.assertIn("1,890", out)

    def test_times_extrapolation_stacked(self):
        code, out, _ = run(["combo", "--drugs", "泰诺,999感冒灵,维C银翘片",
                            "--times", "4"])
        self.assertEqual(code, 4)  # 630×4 = 2520 > 2000
        self.assertIn("2,520", out)
        self.assertIn("判定 STACKED", out)

    def test_no_share_not_guilty(self):
        # 新康泰克(不含酚)+ 美林(布洛芬):无共享成分,机器不做有罪推定
        code, out, _ = run(["combo", "--drugs", "新康泰克,芬必得"])
        self.assertEqual(code, 0)
        self.assertNotIn("共享成分", out)
        self.assertIn("判定 OK", out)

    def test_single_drug_ok(self):
        # 单药说明书满频次:泰诺林 500×4 = 2000 恰线 OK
        code, out, _ = run(["combo", "--drugs", "泰诺林", "--times", "4"])
        self.assertEqual(code, 0)
        self.assertIn("2,000", out)

    def test_unknown_drug(self):
        code, _, err = run(["combo", "--drugs", "泰诺,神仙水"])
        self.assertEqual(code, 2)
        self.assertIn("未知药名", err)

    def test_bad_times(self):
        code, _, err = run(["combo", "--drugs", "泰诺", "--times", "0"])
        self.assertEqual(code, 2)

    def test_alias_check(self):
        code, out, _ = run(["check", "--drugs", "芬必得"])
        self.assertEqual(code, 0)

    def test_caffeine_no_hard(self):
        # 咖啡因只有一层通识线:散利痛+感冒灵 单次 70mg ×3 = 210 OK
        code, out, _ = run(["combo", "--drugs", "散利痛,999感冒灵"])
        self.assertEqual(code, 0)
        self.assertIn("咖啡因", out)


class TestShare(unittest.TestCase):
    def test_index_counts(self):
        code, out, _ = run(["share"])
        self.assertEqual(code, 0)
        self.assertIn("藏在 7 个药盒", out)
        self.assertIn("泰诺325片", out)
        self.assertIn("布洛芬", out)
        self.assertIn("药-成分对 27", out)  # Σ内置成分行数

    def test_ingredient_filter(self):
        code, out, _ = run(["share", "--ingredient", "对乙酰氨基酚"])
        self.assertEqual(code, 0)
        self.assertIn("泰诺325片", out)
        self.assertNotIn("芬必得", out)

    def test_unknown_ingredient(self):
        code, out, _ = run(["share", "--ingredient", "青霉素"])
        self.assertEqual(code, 0)
        self.assertIn("药表里没有含它的药", out)

    def test_custom_meds_join_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "m.tsv")
            with open(p, "w", encoding="utf-8") as f:
                f.write("name\tingredient\tmg\tunit\n"
                        "诊所白瓶药\t对乙酰氨基酚\t300\t片\n")
            code, out, _ = run(["share", "--meds", p,
                                "--ingredient", "对乙酰氨基酚"])
        self.assertEqual(code, 0)
        self.assertIn("诊所白瓶药300片", out)
        self.assertIn("8 个药盒", out)

    def test_alias_where(self):
        code, out, _ = run(["where", "--ingredient", "布洛芬"])
        self.assertEqual(code, 0)


class TestValidate(Base):
    def test_sound(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["validate", p, "--meds", mp])
        self.assertEqual(code, 0)
        self.assertIn("判定 SOUND", out)
        self.assertIn("残差 0.00e+00", out)

    def test_broken_ledger_is_exit2(self):
        p = self.tsv("d.tsv", self.LEDGER + "2026-01-10\t08:00\t神仙水\t1\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)

    def test_expansion_identity_reported(self):
        p = self.tsv("d.tsv", self.LEDGER)
        mp = self.tsv("m.tsv", self.CUSTOM_MEDS)
        code, out, _ = run(["validate", p, "--meds", mp])
        self.assertIn("Σ成分数 == Σ展开事件", out)


if __name__ == "__main__":
    unittest.main()
