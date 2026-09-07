#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kin-ring 验收测试.

每一条都是「年轮」的方法论主张变成的可执行断言:
  * 判线恰线语义(Δ=0 REACHED、Δ=+5 NEAR 恰线亮、Δ=+6 LATER 不亮)
    ——线的全部价值是提前量,不是精确度;
  * REACHED/NEAR/CLUSTER/BROKEN 各管各的案;UNDATABLE/GONE 是辅灯
    不抬闸;子女的病不对齐你的年纪;配偶无血缘单列;
  * 零墙钟:源码无系统时钟,as-of 缺省锚定 # as-of: 声明;都没有则
    时间闸跳过并披露,CLUSTER/BROKEN 照判——宁可不判不装懂;
  * 时间机器:后视(确诊晚于 as-of)如实呈现不参与对齐与聚集——
    未来的确诊不能点亮过去的灯;
  * 恒等式:Σperson≡名册、Σdx≡本人+同住+对齐、簇员守恒、me 锚唯一;
  * 账坏 exit 2(表头/行型/亲属词表/年轮倒转/me 锚),空账薄账
    exit 3,账面带灯 exit 4;同账任何机器任何一天逐字节一致。

跑法: python3 -m unittest discover -s kin-ring/tests -v
"""

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)  # .../kin-ring(规范化,否则 import 解析到目录本身)
CLI = os.path.join(PKG, "kin_ring.py")
sys.path.insert(0, PKG)

import kin_ring  # noqa: E402

run = kin_ring.main

HEADER = "type\tkey\trel\tbirth\tstatus\tdx\tdxyr\tnote"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kin-ring-test-")
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ledger(self, text, name=None):
        # 缺省自动编号:同一测试里多本账互不覆盖
        if name is None:
            self._seq += 1
            name = "kin-%d.tsv" % self._seq
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def ok(self, *argv):
        """期望 exit 0,返回 stdout。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(list(argv))
        self.assertEqual(rc, 0, "期望 exit 0,得到 %d:\n%s" % (rc, buf.getvalue()))
        return buf.getvalue()

    def lights(self, *argv):
        """期望 exit 4(账面带灯),返回 stdout。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run(list(argv))
        self.assertEqual(rc, 4, "期望 exit 4,得到 %d:\n%s" % (rc, buf.getvalue()))
        return buf.getvalue()

    def refusals(self, *argv):
        """期望 exit 3(空账/薄账拒判),返回 stderr。"""
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                run(list(argv))
        self.assertEqual(cm.exception.code, 3)
        return err.getvalue()

    def bad(self, *argv):
        """期望 exit 2(账坏),返回 stderr。"""
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                run(list(argv))
        self.assertEqual(cm.exception.code, 2)
        return err.getvalue()

    def two(self, me_birth="1983", kin=""):
        """最小账本:我 + 任意亲人行;祖辈缺口用 # gone 声明掉(不测 BROKEN)。"""
        return self.ledger(
            "# as-of: 2026-09-07\n# gone: grandparent\n%s\n%s%s"
            % (HEADER,
               ("person\t我\tme\t%s\talive\n" % me_birth), kin))


# ---------------------------------------------------------------- 恰线语义


class ExactLine(Base):
    def test_delta_zero_is_reached(self):
        # 姐姐 1983 生、2013 确诊 = 30 岁;我 1983 生,as-of 2013 → 30 岁,Δ=0
        out = self.lights("report", self.two(
            kin="person\t姐姐\tsibling\t1983\talive\n"
                "dx\t姐姐\t\t\t\t癫痫\t2013\t\n"),
            "--as-of", "2013-06-01")
        self.assertIn("REACHED", out)
        self.assertIn("已到达", out)

    def test_delta_minus_one_is_reached(self):
        out = self.lights("report", self.two(
            kin="person\t姐姐\tsibling\t1983\talive\n"
                "dx\t姐姐\t\t\t\t癫痫\t2013\t\n"),
            "--as-of", "2014-06-01")
        self.assertIn("REACHED", out)
        self.assertNotIn("🟡 NEAR", out)

    def test_delta_plus_five_is_near_exact_line(self):
        # 姐姐 1973 生,2013 确诊 = 40 岁;我 2018 年 35 → Δ=+5,恰线亮 NEAR
        out = self.lights("report", self.two(
            kin="person\t姐姐\tsibling\t1973\talive\n"
                "dx\t姐姐\t\t\t\t癫痫\t2013\t\n"),
            "--as-of", "2018-06-01")
        self.assertIn("🟡 NEAR", out)
        self.assertNotIn("🔴 REACHED", out)

    def test_delta_plus_six_is_later_no_lights(self):
        # 同一本账,2017 年我 34 → Δ=+6,出带不亮
        out = self.ok("report", self.two(
            kin="person\t姐姐\tsibling\t1973\talive\n"
                "dx\t姐姐\t\t\t\t癫痫\t2013\t\n"),
            "--as-of", "2017-06-01")
        self.assertNotIn("🔴 REACHED", out)
        self.assertNotIn("🟡 NEAR", out)
        self.assertIn("LATER", out)


# ---------------------------------------------------------------- as-of / 零墙钟


class Clock(Base):
    LED = ("# as-of: 2026-09-07\n# gone: grandparent\n" + HEADER + "\n"
           "person\t我\tme\t1983\talive\n"
           "person\t哥哥\tsibling\t1979\talive\n"
           "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")

    def test_as_of_from_declaration(self):
        out = self.lights("report", self.ledger(self.LED))
        self.assertIn("# as-of: 声明", out)
        self.assertIn("今年 43", out)

    def test_cli_as_of_overrides_declaration(self):
        out = self.ok("report", self.ledger(self.LED), "--as-of", "2012-01-01")
        self.assertIn("--as-of", out)
        self.assertIn("今年 29", out)
        self.assertIn("后视", out)  # 2021 确诊晚于 2012 → 后视跳过
        self.assertNotIn("🔴 REACHED", out)

    def test_no_clock_skips_time_gates_and_discloses(self):
        led = self.ledger("# gone: grandparent\n" + HEADER
                          + "\nperson\t我\tme\t1983\talive\n"
                          "person\t哥哥\tsibling\t1979\talive\n"
                          "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")
        out = self.ok("report", led)
        self.assertIn("未钉死", out)
        self.assertIn("跳过", out)
        self.assertIn("无钟", out)

    def test_no_clock_cluster_still_judges(self):
        led = self.ledger(HEADER + "\nperson\t我\tme\t1983\talive\n"
                          "person\t父亲\tparent\t1952\talive\n"
                          "person\t哥哥\tsibling\t1979\talive\n"
                          "dx\t父亲\t\t\t\t2型糖尿病\t2000\t\n"
                          "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")
        out = self.lights("report", led)
        self.assertIn("CLUSTER", out)

    def test_broken_date_format_rejected(self):
        led = self.ledger("# as-of: 2026-9-7\n" + HEADER + "\n"
                          "person\t我\tme\t1983\talive\n"
                          "person\t哥哥\tsibling\t1979\talive\n"
                          "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")
        self.bad("report", led)

    def test_duplicate_as_of_declaration_rejected(self):
        led = self.ledger("# as-of: 2026-09-07\n# as-of: 2026-09-08\n"
                          + HEADER + "\nperson\t我\tme\t1983\talive\n"
                          "person\t哥哥\tsibling\t1979\talive\n"
                          "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")
        self.bad("report", led)

    def test_year_granularity_arithmetic(self):
        # 2026-12-31 与 2026-01-01 同年:公历年差,粒度±1,不做月龄
        for day in ("2026-01-01", "2026-12-31"):
            out = self.lights("report", self.ledger(self.LED),
                              "--as-of", day)
            self.assertIn("今年 43", out)


# ---------------------------------------------------------------- 后视时间机器


class TimeMachine(Base):
    LED = ("# as-of: 2026-09-07\n# gone: grandparent\n" + HEADER + "\n"
           "person\t我\tme\t1983\talive\n"
           "person\t父亲\tparent\t1952\talive\n"
           "person\t哥哥\tsibling\t1979\talive\n"
           "dx\t父亲\t\t\t\t2型糖尿病\t2000\t\n"
           "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")

    def test_future_dx_shown_but_skipped(self):
        out = self.ok("report", self.ledger(self.LED), "--as-of", "2012-01-01")
        self.assertIn("后视", out)
        self.assertIn("如实呈现", out)

    def test_future_dx_does_not_light_cluster(self):
        # 2012 视角:哥哥 2021 是未来,簇只剩父亲一条 → 不亮
        out = self.ok("report", self.ledger(self.LED), "--as-of", "2012-01-01")
        self.assertIn("(无聚集)", out)

    def test_both_dx_past_cluster_lights(self):
        out = self.lights("report", self.ledger(self.LED))
        self.assertIn("CLUSTER", out)
        self.assertIn("2型糖尿病 ×2", out)


# ---------------------------------------------------------------- 灯语义


class Lamps(Base):
    def base(self, extra_kin="", me="1983", asof="2026-09-07"):
        return self.ledger("# as-of: %s\n%s\nperson\t我\tme\t%s\talive\n%s"
                           % (asof, HEADER, me, extra_kin))

    def test_undatable_missing_birth(self):
        # UNDATABLE 不抬闸(exit 4 是 REACHED/NEAR/CLUSTER/BROKEN 的事)
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t爷爷\tgrandparent\t?\tdead:1998\n"
            "dx\t爷爷\t\t\t\t卒中\t1955\t\n"))
        self.assertIn("UNDATABLE", out)
        self.assertIn("见 ask 清单", out)

    def test_child_dx_never_aligns(self):
        # 儿子 2010 生、2024 确诊(14 岁);我 43——不是「我已到达 14 岁」,
        # 是家系证据:不亮 REACHED/NEAR,进 CLUSTER 一级
        out = self.lights("report", self.base(
            "person\t儿子\tchild\t2010\talive\n"
            "person\t弟弟\tsibling\t1985\talive\n"
            "dx\t儿子\t\t\t\t1型糖尿病\t2024\t\n"
            "dx\t弟弟\t\t\t\t1型糖尿病\t2020\t\n"))
        self.assertIn("家系证据", out)
        self.assertIn("CLUSTER", out)

    def test_spouse_dx_is_separate_lane(self):
        out = self.ok("report", self.base(
            "# gone: grandparent\n" +
            "person\t妻子\tspouse\t1985\talive\n"
            "dx\t妻子\t\t\t\t乳腺癌\t2023\t\n"))
        self.assertNotIn("🔴 REACHED", out)
        self.assertIn("本人与同住人", out)
        self.assertIn("配偶", out)

    def test_self_dx_own_lane(self):
        out = self.ok("report", self.base(
            "# gone: grandparent\n" +
            "dx\t我\t\t\t\t甲状腺癌\t2024\t\n"))
        self.assertIn("本人", out)
        self.assertNotIn("🔴 REACHED", out)

    def test_cluster_two_first_degree(self):
        out = self.lights("report", self.base(
            "person\t父亲\tparent\t1952\talive\n"
            "person\t哥哥\tsibling\t1979\talive\n"
            "dx\t父亲\t\t\t\t2型糖尿病\t2000\t\n"
            "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n"))
        self.assertIn("CLUSTER", out)
        self.assertIn("含一级亲属 2 条", out)

    def test_cluster_two_second_degree_disclosed_not_lit(self):
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t姑妈\tuncle-aunt\t1948\talive\n"
            "person\t舅舅\tuncle-aunt\t1950\talive\n"
            "dx\t姑妈\t\t\t\t2型糖尿病\t1998\t\n"
            "dx\t舅舅\t\t\t\t2型糖尿病\t2005\t\n"))
        self.assertNotIn("🔴 CLUSTER", out)
        self.assertIn("披露不亮灯", out)
        self.assertIn("一级亲属才算聚集门槛", out)

    def test_cluster_normalization_fullwidth_space_case(self):
        out = self.lights("report", self.base(
            "person\t父亲\tparent\t1952\talive\n"
            "person\t哥哥\tsibling\t1979\talive\n"
            "dx\t父亲\t\t\t\t２型糖尿病\t2000\t\n"   # 全角 2
            "dx\t哥哥\t\t\t\t 2 型糖尿病 \t2021\t\n"))  # 空格混排
        self.assertIn("CLUSTER", out)
        self.assertIn("×2", out)

    def test_cluster_no_synonym_invention(self):
        # 「II型」≠「2型」——机器不发明没教过的医学同义
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t姑妈\tuncle-aunt\t1948\talive\n"
            "person\t舅舅\tuncle-aunt\t1950\talive\n"
            "dx\t姑妈\t\t\t\tII型糖尿病\t1998\t\n"
            "dx\t舅舅\t\t\t\t2型糖尿病\t2005\t\n"))
        self.assertIn("(无聚集)", out)

    def test_broken_no_grandparents(self):
        out = self.lights("report", self.base(
            "person\t父亲\tparent\t1952\talive\n"
            "dx\t父亲\t\t\t\t高血压\t1998\t\n"))
        self.assertIn("BROKEN", out)
        self.assertIn("失去最后的证人", out)

    def test_gone_declaration_overrides_broken(self):
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t父亲\tparent\t1952\talive\n"
            "dx\t父亲\t\t\t\t高血压\t2005\t\n"))
        self.assertNotIn("BROKEN", out)
        self.assertIn("GONE", out)
        self.assertIn("不再追问", out)

    def test_gone_declaration_conflict_disclosed(self):
        # 声明了 gone 却有祖辈在账:如实披露矛盾,不静默吞掉
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t爷爷\tgrandparent\t1925\tdead:1998\n"
            "dx\t爷爷\t\t\t\t卒中\t1985\t\n"))
        self.assertIn("声明与事实不符", out)

    def test_spouse_and_self_never_fire_cluster(self):
        # 夫妻同病 ≠ 家系聚集:本人/同住人不进簇
        out = self.ok("report", self.base(
            "# gone: grandparent\n"
            "person\t妻子\tspouse\t1985\talive\n"
            "dx\t我\t\t\t\t2型糖尿病\t2024\t\n"
            "dx\t妻子\t\t\t\t2型糖尿病\t2023\t\n"))
        self.assertIn("(无聚集)", out)

    def test_dx_year_before_birth_is_bad_ledger(self):
        self.bad("report", self.base(
            "person\t父亲\tparent\t1952\talive\n"
            "dx\t父亲\t\t\t\t高血压\t1940\t\n"))

    def test_rel_alias_chinese_accepted(self):
        out = self.ok("report", self.base(
            "person\t爷爷\t爷爷\t1925\tdead:1998\n"
            "dx\t爷爷\t\t\t\t卒中\t1985\t\n"))
        self.assertIn("祖辈(二级)", out)


# ---------------------------------------------------------------- 账坏 / 空账 / 薄账


class LedgerHygiene(Base):
    ME = "person\t我\tme\t1983\talive\n"
    KIN = ("person\t哥哥\tsibling\t1979\talive\n"
           "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")

    def test_missing_file(self):
        self.bad("report", os.path.join(self.dir, "nope.tsv"))

    def test_missing_header(self):
        self.bad("report", self.ledger(self.ME + self.KIN))

    def test_wrong_header(self):
        self.bad("report", self.ledger("type\tkey\n" + self.ME + self.KIN))

    def test_unknown_row_type(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "med\t哥哥\t阿司匹林\n"))

    def test_unknown_rel(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t邻居\tneighbour\t1950\talive\n"
                                       + self.KIN))

    def test_me_birth_unknown(self):
        self.bad("report", self.ledger(HEADER + "\n"
                                       + "person\t我\tme\t?\talive\n" + self.KIN))

    def test_me_dead_rejected(self):
        self.bad("report", self.ledger(HEADER + "\n"
                                       + "person\t我\tme\t1983\tdead:2099\n" + self.KIN))

    def test_two_me_rejected(self):
        self.bad("report", self.ledger(HEADER + "\n"
                                       + "person\t我\tme\t1983\talive\n"
                                       + "person\t我也\tme\t1984\talive\n" + self.KIN))

    def test_duplicate_person_key(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t哥哥\tsibling\t1979\talive\n"
                                       + "person\t哥哥\tsibling\t1980\talive\n"
                                       + "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n"))

    def test_dx_unknown_person(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "dx\t三叔\t\t\t\t卒中\t1990\t\n"))

    def test_dx_missing_name(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t哥哥\tsibling\t1979\talive\n"
                                       + "dx\t哥哥\t\t\t\t\t2021\t\n"))

    def test_death_before_birth(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t爷爷\tgrandparent\t1925\tdead:1900\n"
                                       + self.KIN))

    def test_year_out_of_range(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t爷爷\tgrandparent\t0999\tdead:1998\n"
                                       + self.KIN))

    def test_year_five_digits(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person\t爷爷\tgrandparent\t11925\tdead:1998\n"
                                       + self.KIN))

    def test_too_many_columns(self):
        self.bad("report", self.ledger(
            HEADER + "\n" + self.ME + self.KIN.rstrip("\n") + "\t多出来的一列\n"))

    def test_trailing_columns_optional(self):
        # 手编日常:右侧缺列视为空,不报错
        out = self.lights("report", self.ledger(
            HEADER + "\n" + self.ME
            + "person\t哥哥\tsibling\t1979\talive\n"
            + "dx\t哥哥\t\t\t\t2型糖尿病\t2021"))
        self.assertIn("REACHED", out)

    def test_non_tsv_row(self):
        self.bad("report", self.ledger(HEADER + "\n" + self.ME
                                       + "person,哥哥,sibling,1979,alive\n"))

    def test_gone_unknown_rel(self):
        self.bad("report", self.ledger(
            "# gone: 隔壁老王\n" + HEADER + "\n" + self.ME + self.KIN))

    def test_empty_ledger(self):
        self.refusals("report", self.ledger(""))

    def test_comment_only_ledger(self):
        self.refusals("report", self.ledger("# 只有一句注释\n"))

    def test_header_only_ledger(self):
        self.refusals("report", self.ledger(HEADER + "\n"))

    def test_thin_ledger_me_only(self):
        self.refusals("report", self.ledger(HEADER + "\n" + self.ME))

    def test_no_me_rejected(self):
        # 有人有病史、没有主角:账坏不是薄账——替谁记,谁就是 me
        self.bad("report", self.ledger(HEADER + "\n"
                                       + "person\t哥哥\tsibling\t1979\talive\n"
                                       + "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n"))


# ---------------------------------------------------------------- kin / ask


class KinAndAsk(Base):
    LED = ("# as-of: 2026-09-07\n# gone: grandparent\n" + HEADER + "\n"
           "person\t我\tme\t1983\talive\n"
           "person\t母亲\tparent\t1955\talive\n"
           "person\t爷爷\tgrandparent\t1925\tdead:1998\n"
           "dx\t爷爷\t\t\t\t卒中\t?\t\n"
           "dx\t我\t\t\t\t甲状腺癌\t2024\t\n")

    def test_kin_roster_counts(self):
        out = self.ok("kin", self.ledger(self.LED))
        self.assertIn("病史 1", out)
        self.assertIn("故于 1998", out)
        self.assertIn("各辈覆盖", out)

    def test_kin_zero_dx_elder_disclosed(self):
        out = self.ok("kin", self.ledger(self.LED))
        self.assertIn("母亲——真的没有,还是没问过?", out)

    def test_kin_grandparent_gap(self):
        out = self.ok("kin", self.ledger(self.LED))
        self.assertIn("祖辈仅 1 位在账", out)

    def test_ask_undatable_question(self):
        out = self.ok("ask", self.ledger(self.LED))
        self.assertIn("爷爷的卒中是哪一年确诊的?他当时多少岁?", out)

    def test_ask_birth_question_when_birth_unknown(self):
        led = ("# as-of: 2026-09-07\n" + HEADER + "\n"
               "person\t我\tme\t1983\talive\n"
               "person\t姥姥\tgrandparent\t?\tdead:2010\n"
               "dx\t姥姥\t\t\t\t卒中\t1980\t\n")
        out = self.ok("ask", self.ledger(led))
        self.assertIn("姥姥哪一年出生?", out)

    def test_ask_zero_dx_elder(self):
        out = self.ok("ask", self.ledger(self.LED))
        self.assertIn("母亲在账至今零确诊", out)

    def test_ask_broken_prompt(self):
        led = ("# as-of: 2026-09-07\n" + HEADER + "\n"
               "person\t我\tme\t1983\talive\n"
               "person\t父亲\tparent\t1952\talive\n"
               "dx\t父亲\t\t\t\t高血压\t1998\t\n")
        out = self.ok("ask", self.ledger(led))
        self.assertIn("祖辈整辈空白", out)
        self.assertIn("# gone: grandparent", out)

    def test_ask_no_gap(self):
        led = ("# gone: grandparent\n# as-of: 2026-09-07\n" + HEADER + "\n"
               "person\t我\tme\t1983\talive\n"
               "person\t父亲\tparent\t1952\talive\n"
               "dx\t父亲\t\t\t\t高血压\t1998\t\n")
        out = self.ok("ask", self.ledger(led))
        self.assertIn("没有待问的缺口", out)

    def test_kin_ask_exit_zero_even_with_lights(self):
        # kin/ask 是清单不是判级:恒 exit 0,判级是 report 的事
        path = self.ledger(self.LED)
        self.assertEqual(run(["kin", path]), 0)
        self.assertEqual(run(["ask", path]), 0)


# ---------------------------------------------------------------- validate / 恒等式


class Validate(Base):
    LED = ("# as-of: 2026-09-07\n# gone: grandparent\n" + HEADER + "\n"
           "person\t我\tme\t1983\talive\n"
           "person\t父亲\tparent\t1952\talive\n"
           "person\t哥哥\tsibling\t1979\talive\n"
           "person\t妻子\tspouse\t1985\talive\n"
           "dx\t我\t\t\t\t甲状腺癌\t2024\t\n"
           "dx\t妻子\t\t\t\t乳腺癌\t2023\t\n"
           "dx\t父亲\t\t\t\t2型糖尿病\t2000\t\n"
           "dx\t哥哥\t\t\t\t2型糖尿病\t2021\t\n")

    def test_validate_ok_and_identities(self):
        out = self.ok("validate", self.ledger(self.LED))
        self.assertIn("4 ≡ 1+1+2", out)          # Σdx ≡ 本人+同住+对齐
        self.assertIn("簇员守恒", out)
        self.assertIn("2 ≡ 2", out)              # Σ簇大小 ≡ 参与聚集 dx
        self.assertIn("双路径重放", out)
        self.assertIn("逐字节一致", out)

    def test_validate_reports_lamp_state(self):
        out = self.ok("validate", self.ledger(self.LED))
        self.assertIn("REACHED/NEAR 2", out)     # 父 48 Δ+2、哥 42 Δ−1
        self.assertIn("CLUSTER 亮 1 簇", out)


# ---------------------------------------------------------------- 确定性 / dogfood


class Determinism(Base):
    def sample_path(self):
        return os.path.join(PKG, "examples", "kin.tsv")

    def test_byte_identical_reruns(self):
        path = self.sample_path()
        outs = []
        for _ in range(2):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(run(["report", path]), 4)
            outs.append(buf.getvalue())
        self.assertEqual(outs[0], outs[1])

    def test_report_only_basename(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(run(["report", self.sample_path()]), 4)
        self.assertNotIn(PKG, buf.getvalue())
        self.assertIn("账本: kin.tsv", buf.getvalue())

    def test_examples_byte_check(self):
        proc = subprocess.run(
            [sys.executable,
             os.path.join(PKG, "examples", "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_sample_report_has_expected_anatomy(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(run(["report", self.sample_path()]), 4)
        out = buf.getvalue()
        self.assertIn("🔴 REACHED", out)         # 哥哥 42 确诊,我 43
        self.assertIn("还差 5 年", out)          # 父亲糖尿病 48,恰线
        self.assertIn("🔴 CLUSTER  2型糖尿病 ×2", out)
        self.assertIn("UNDATABLE", out)          # 爷爷卒中
        self.assertIn("本人", out)               # 甲状腺癌 SELF 通道
        self.assertNotIn("BROKEN", out)          # 爷爷在账,不亮

    def test_sample_asof_2012_all_dark(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(run(["report", self.sample_path(),
                                  "--as-of", "2012-06-01"]), 0)
        out = buf.getvalue()
        self.assertNotIn("🔴 REACHED", out)
        self.assertIn("后视", out)
        self.assertIn("今年 29", out)

    def test_source_has_no_wall_clock(self):
        with open(CLI, "r", encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("datetime", "time.", "now(", "utcnow",
                       "strftime", "localtime"):
            self.assertNotIn(banned, src, "源码不得引用墙钟: %s" % banned)

    def test_no_subcommand_shows_help_exit_2(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            rc = run([])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
