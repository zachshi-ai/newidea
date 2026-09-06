#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handoff 验收测试.

每一条都是「交底」的方法论主张变成的可执行断言:
  * 判级恰线语义(STALE 恰 ttl 天不亮、731 天才亮)——线画在保守线
    上的意义是提前量,不是精确度;
  * STALE/SOLO/NO-TRACE 三灯各管各的案,MISSING 是类别灯不是账坏;
  * 时间机器翻的是灯,不是清单——verified 晚于 as-of 如实呈现、
    清单恒不隐去,Σ六类件数 ≡ 条目数任何视角下都闭合;
  * 零墙钟:源码无系统时钟,as-of 缺省锚定 # checked: 盘点日声明;
  * 打码幂等 mask∘mask=mask、条目守恒;交接卡行号回溯 100%。

跑法: python3 -m unittest discover -s handoff/tests -v
"""

import contextlib
import datetime as dt
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)  # .../handoff(规范化,否则 import 解析到目录本身)
CLI = os.path.join(PKG, "handoff.py")
sys.path.insert(0, PKG)

import handoff  # noqa: E402

run = handoff.main


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="handoff-test-")
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ledger(self, text, name=None):
        # 缺省自动编号:同一测试里多本账互不覆盖
        if name is None:
            self._seq += 1
            name = "handoff-%d.tsv" % self._seq
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_ok(self, argv):
        """跑一个预期 exit 0 的命令,返回 stdout。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run(argv)
        self.assertEqual(code, 0, "expected exit 0, got %s:\n%s" % (code, buf.getvalue()))
        return buf.getvalue()

    def run_code(self, argv):
        """跑一个命令,返回 (exit, stdout, stderr)。"""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run(argv)
        return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- 账本

HDR = ("category\ttitle\tscale\twhere\tkey_clue\tknows\tverified"
       "\tstep\turgent\tnote\n")

def row(title="工资卡", cat="bank", scale="w", where="抽屉", clue="密码本",
        knows="spouse", verified="2026-09-01", step="网点", urgent="", note=""):
    cells = [cat, title, scale, where, clue, knows, verified, step, urgent, note]
    return "\t".join(cells) + "\n"


def full_ledger(rows, checked="2026-09-06"):
    head = "# 交底账本\n# checked: %s\n" % checked if checked else "# 交底账本\n"
    return head + HDR + "".join(rows)


# 六类齐全、全绿、无 SOLO 的账本(盘一盘灯语义的「对照臂」)
CLEAN_ROWS = [
    row("工行卡", cat="bank", knows="spouse"),
    row("基金", cat="invest", knows="family"),
    row("重疾险", cat="policy", knows="spouse"),
    row("房产证", cat="deed", knows="spouse"),
    row("借条(别人欠我)", cat="debt", knows="spouse"),
    row("邮箱", cat="digital", knows="kids"),
]


def six(rows):
    """六类齐全的对照臂 + 被测行——孤立测一盏灯时,别让 MISSING 抢戏。"""
    return full_ledger(CLEAN_ROWS + rows)


EX_DIR = os.path.join(PKG, "examples")


class TestLoad(Base):
    def test_row_count_and_physical_lineno(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        items, checked = handoff.load_ledger(p)
        self.assertEqual(len(items), 6)
        # 表头在第 3 行 → 第一条数据物理行号 4
        self.assertEqual([it.line_no for it in items], [4, 5, 6, 7, 8, 9])

    def test_chinese_header_same_effect(self):
        zh = ("类别\t名目\t量级\t位置\t线索\t谁知道\t核实\t第一步\t急\t注\n"
              "bank\t工行卡\tw\t抽屉\t密码本\tspouse\t2026-09-01\t网点\t\t\n")
        p = self.ledger("# c\n" + zh)
        items, _ = handoff.load_ledger(p)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "bank")

    def test_column_order_free(self):
        shuffled = ("title\tcategory\tverified\tscale\tknows\twhere\tkey_clue\n"
                    "工行卡\tbank\t2026-09-01\tw\tspouse\t抽屉\t密码本\n")
        p = self.ledger("# c\n" + shuffled)
        items, _ = handoff.load_ledger(p)
        self.assertEqual(items[0].title, "工行卡")
        self.assertEqual(items[0].verified, dt.date(2026, 9, 1))

    def test_trailing_tab_tolerated(self):
        p = self.ledger("# c\n" + HDR + row("工行卡").rstrip("\n") + "\t\n")
        items, _ = handoff.load_ledger(p)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].note, "")

    def test_optional_columns_can_be_absent(self):
        mini = "category\ttitle\tscale\twhere\tkey_clue\tknows\tverified\n" \
               "bank\t工行卡\tw\t抽屉\t密码本\tspouse\t2026-09-01\n"
        p = self.ledger("# c\n" + mini)
        items, _ = handoff.load_ledger(p)
        self.assertEqual(items[0].step, "")
        self.assertFalse(items[0].urgent)

    def test_checked_trail_kept_in_order(self):
        text = full_ledger(CLEAN_ROWS, checked="2024-02-10")
        text = text.replace("# checked: 2024-02-10",
                            "# checked: 2024-02-10\n# checked: 2026-09-06")
        _, checked = handoff.load_ledger(self.ledger(text))
        self.assertEqual([c.isoformat() for c in checked],
                         ["2024-02-10", "2026-09-06"])

    def test_aliases(self):
        p = self.ledger("# c\n" + HDR +
                        row("a", cat="保单", scale="百万", knows="只有我", urgent="急"))
        items, _ = handoff.load_ledger(p)
        self.assertEqual(items[0].category, "policy")
        self.assertEqual(items[0].scale, "hw")
        self.assertEqual(items[0].knows, "self-only")
        self.assertTrue(items[0].urgent)

    def test_category_case_insensitive(self):
        p = self.ledger("# c\n" + HDR + row("a", cat="Deed"))
        items, _ = handoff.load_ledger(p)
        self.assertEqual(items[0].category, "deed")


class TestBad(Base):
    def bad(self, body, checked="2026-09-06"):
        p = self.ledger(full_ledger([row("ok")], checked=checked) +
                        body if checked else body)
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD, err)
        self.assertIn("账坏", err)

    def test_date_needs_zero_padding(self):
        self.bad("bank\ta\tw\tw\tc\tspouse\t2026-9-6\n")

    def test_date_calendar_rejected(self):
        self.bad("bank\ta\tw\tw\tc\tspouse\t2026-02-30\n")

    def test_bad_category(self):
        self.bad("股票账户\ta\tw\tw\tc\tspouse\t2026-09-01\n")

    def test_bad_scale(self):
        self.bad("bank\ta\t千万\tw\tc\tspouse\t2026-09-01\n")

    def test_bad_knows(self):
        self.bad("bank\ta\tw\tw\tc\t所有人\t2026-09-01\n")

    def test_bad_urgent(self):
        self.bad("bank\ta\tw\tw\tc\tspouse\t2026-09-01\t网点\t非常急\t\n")

    def test_empty_title(self):
        self.bad("bank\t\tw\tw\tc\tspouse\t2026-09-01\n")

    def test_empty_verified(self):
        self.bad("bank\ta\tw\tw\tc\tspouse\t\n")

    def test_unknown_header_column(self):
        p = self.ledger("# c\nsecret\ttitle\nx\ty\n")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("不是已知列", err)

    def test_missing_required_column(self):
        p = self.ledger("# c\ncategory\ttitle\nbank\t工行卡\n")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("缺必需列", err)

    def test_duplicate_column(self):
        p = self.ledger("# c\ncategory\ttitle\ttitle\tverified\tscale\tknows"
                        "\twhere\tkey_clue\n")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("重复", err)

    def test_field_count_mismatch(self):
        p = self.ledger("# c\n" + HDR + "bank\t只有五个字段\t还行\n")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("字段数", err)

    def test_no_header(self):
        # 只有注释 = 有内容但无表头 = 账坏(表头都没定的账,列义无从谈起)
        p = self.ledger("# 只有注释,没有表头\n")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("表头", err)

    def test_bad_checked_declaration(self):
        p = self.ledger("# checked: 2026-9-6\n" + HDR + row())
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("账坏", err)

    def test_ledger_missing(self):
        code, _, err = self.run_code(["report", os.path.join(self.dir, "nope.tsv")])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("不存在", err)

    def test_negative_ttl(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        code, _, err = self.run_code(["report", p, "--ttl", "-1"])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("--ttl", err)

    def test_negative_top(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        code, _, err = self.run_code(["brief", p, "--top", "-3"])
        self.assertEqual(code, handoff.EXIT_BAD)
        self.assertIn("--top", err)


class TestEmpty(Base):
    def test_zero_byte_file(self):
        p = self.ledger("")
        code, _, err = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_EMPTY)
        self.assertIn("空账", err)

    def test_blank_lines_only(self):
        p = self.ledger("\n\n")
        code, _, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_EMPTY)

    def test_header_without_rows(self):
        p = self.ledger("# c\n" + HDR)
        code, _, err = self.run_code(["brief", p])
        self.assertEqual(code, handoff.EXIT_EMPTY)

    def test_all_commands_refuse_empty(self):
        p = self.ledger("# c\n" + HDR)
        for argv in (["report", p], ["brief", p], ["who", p], ["validate", p]):
            code, _, _ = self.run_code(argv)
            self.assertEqual(code, handoff.EXIT_EMPTY, argv)


class TestStale(Base):
    def exact_days_before(self, days):
        """verified = as_of - days 的一件要紧物,六类对照臂打底。"""
        as_of = dt.date(2026, 9, 6)
        v = (as_of - dt.timedelta(days=days)).isoformat()
        return self.ledger(six([row("老基金", cat="invest", verified=v)]))

    def test_exact_line_not_lit(self):
        out = self.run_ok(["report", self.exact_days_before(730)])
        self.assertIn("带灯 0", out)
        self.assertIn("全部绿灯", out)
        # 灯区(报告尾部)没有 STALE 判级行——头部"STALE 线"元数据不算灯
        self.assertNotIn("STALE", out.split("带灯清单")[1])

    def test_one_day_past_line_lit(self):
        code, out, _ = self.run_code(["report", self.exact_days_before(731)])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("STALE", out)
        self.assertIn("距 as-of 731 天 > 730", out)

    def test_ttl_flag_overrides(self):
        # 730 天前核实:默认线不亮;--ttl 365 翻案后亮——先验全部是旗标
        p = self.exact_days_before(730)
        code, out, _ = self.run_code(["report", p, "--ttl", "365"])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("STALE 线: 365 天", out)
        self.assertIn("距 as-of 730 天 > 365", out)

    def test_ttl_zero_lights_everything_past(self):
        code, out, _ = self.run_code(["report", self.exact_days_before(1),
                                      "--ttl", "0"])
        self.assertEqual(code, handoff.EXIT_LIGHTS)

    def test_no_checked_and_no_asof_skips_gate(self):
        # 无盘点日声明:SOLO/NO-TRACE 照出,STALE 跳过并披露——不借墙钟装懂
        as_of = dt.date(2026, 9, 6)
        v = (as_of - dt.timedelta(days=3000)).isoformat()
        p = self.ledger("# 无声明\n" + HDR + "".join(CLEAN_ROWS) +
                        row("老基金", cat="invest", where="", clue="",
                            knows="self-only", verified=v))
        code, out, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("STALE 闸: 跳过", out)
        self.assertNotIn("STALE ", out.replace("STALE 闸", ""))
        self.assertIn("SOLO", out)
        self.assertIn("NO-TRACE", out)

    def test_no_checked_but_asof_pinned_still_judges(self):
        v = (dt.date(2024, 2, 10) - dt.timedelta(days=800)).isoformat()
        p = self.ledger("# 无声明\n" + HDR + "".join(CLEAN_ROWS) +
                        row("老基金", cat="invest", verified=v))
        code, out, _ = self.run_code(["report", p, "--as-of", "2024-02-10"])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("STALE", out)

    def test_future_verified_not_lit_and_list_kept(self):
        # 时间机器:verified 晚于 as-of 如实不亮;条目计数与「最新核实」
        # 列如实呈现——时间机器翻的是灯,不是清单
        p = self.ledger(six([row("将来才核实的卡", verified="2027-01-01")]))
        code, out, _ = self.run_code(["report", p, "--as-of", "2026-09-06"])
        self.assertEqual(code, handoff.EXIT_OK)
        self.assertIn("7 件", out)
        self.assertIn("最新核实 2027-01-01", out)


class TestSoloAndNoTrace(Base):
    def test_solo_solo(self):
        p = self.ledger(six([row("只有我知道的基金", knows="self-only")]))
        code, out, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("SOLO", out)

    def test_spouse_not_solo(self):
        p = self.ledger(six([row("工资卡", knows="spouse")]))
        out = self.run_ok(["report", p])
        self.assertNotIn("SOLO", out)

    def test_no_trace_needs_both_empty(self):
        # 只空 where 有 clue → 不亮;只空 clue 有 where → 不亮;全空 → 亮
        p1 = self.ledger(six([row("a", where="", clue="密码本第2页")]))
        p2 = self.ledger(six([row("a", where="抽屉", clue="")]))
        p3 = self.ledger(six([row("a", where="", clue="")]))
        for p in (p1, p2):
            code, out, _ = self.run_code(["report", p])
            self.assertNotIn("NO-TRACE", out)
        code, out, _ = self.run_code(["report", p3])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("NO-TRACE", out)

    def test_multi_lamp_one_row(self):
        p = self.ledger(six([row("a", where="", clue="",
                                 knows="self-only",
                                 verified="2019-01-01")]))
        code, out, _ = self.run_code(["report", p])
        self.assertIn("STALE SOLO NO-TRACE", out)


class TestCoverage(Base):
    def test_missing_category_questioned(self):
        # CLEAN_ROWS 缺 digital → 反问句点名
        rows = [r for r in CLEAN_ROWS if "邮箱" not in r]
        p = self.ledger(full_ledger(rows))
        code, out, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("MISSING", out)
        self.assertIn("digital 数字账号", out)
        self.assertIn("邮箱、网盘、代扣订阅", out)

    def test_all_six_present_no_missing(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["report", p])
        self.assertIn("六类齐全", out)
        self.assertNotIn("MISSING", out)

    def test_sum_of_categories_equals_items(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["report", p])
        self.assertIn("6 件", out)

    def test_scale_distribution_line(self):
        p = self.ledger(six([row("大件", scale="hw")]))
        out = self.run_ok(["report", p])
        self.assertIn("k×0 w×6 tw×0 hw×1 na×0", out)

    def test_missing_alone_is_lights(self):
        p = self.ledger(full_ledger([row("工行卡", cat="bank")]))
        code, out, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)  # 五类 MISSING
        self.assertIn("带灯 0", out)


class TestBrief(Base):
    def setUp(self):
        super().setUp()
        # 六类对照臂(行4-9,全绿) + 四件被测物(行10-13)
        rows = [
            row("普通第三件", cat="bank"),                       # 行10
            row("急件二", cat="policy", urgent="y"),             # 行11
            row("普通第四件", cat="deed"),                       # 行12
            row("急件一", cat="digital", urgent="y"),            # 行13
        ]
        self.p = self.ledger(six(rows))
        self.lineno = {"普通第三件": "10", "急件二": "11",
                       "普通第四件": "12", "急件一": "13"}

    def test_urgent_first_then_lineno(self):
        out = self.run_ok(["brief", self.p, "--top", "0"])
        order = re.findall(r"\d+\.\[行\s*(\d+)\]", out)
        # 两件急件(行11,13)最前,其余对照臂+被测按行号
        self.assertEqual(order, ["11", "13", "4", "5", "6", "7", "8", "9", "10", "12"])

    def test_top_truncates(self):
        out = self.run_ok(["brief", self.p, "--top", "2"])
        order = re.findall(r"\d+\.\[行\s*(\d+)\]", out)
        self.assertEqual(order, ["11", "13"])

    def test_top_beyond_count_shows_all(self):
        out = self.run_ok(["brief", self.p, "--top", "99"])
        self.assertEqual(len(re.findall(r"\[行\s*\d+\]", out)), 10)

    def test_lineno_backtracks_into_file(self):
        out = self.run_ok(["brief", self.p, "--top", "0"])
        with open(self.p, encoding="utf-8") as f:
            lines = f.read().split("\n")
        for ln, title in re.findall(r"\[行\s*(\d+)\]\S*\s+(\S+)", out):
            self.assertTrue(lines[int(ln) - 1].startswith(title[0]),
                            "行%s 应是被测数据行" % ln)

    def test_mask_masks_long_digits(self):
        p = self.ledger(six([row("工行卡(尾号6621)", clue="密码本第3页,手机尾号8801",
                                 urgent="y")]))
        out = self.run_ok(["brief", p, "--top", "1", "--mask"])
        self.assertIn("尾号****", out)
        self.assertNotIn("6621", out)
        self.assertNotIn("8801", out)

    def test_mask_keeps_short_numbers(self):
        p = self.ledger(six([row("5万借条", clue="第3页", urgent="y")]))
        out = self.run_ok(["brief", p, "--top", "1", "--mask"])
        self.assertIn("5万借条", out)
        self.assertIn("第3页", out)

    def test_report_does_not_mask(self):
        # report 是本人看的盘点,不打码——打码只属于 brief --mask
        p = self.ledger(six([row("工行卡(尾号6621)", verified="2019-01-01")]))
        code, out, _ = self.run_code(["report", p])
        self.assertIn("尾号6621", out)

    def test_mask_idempotent(self):
        for s in ("尾号6621", "abc12345def", "1234 5678", "第3页", "no digits"):
            self.assertEqual(handoff.mask(handoff.mask(s)), handoff.mask(s))

    def test_stale_shown_as_verify_first(self):
        p = self.ledger(six([row("旧卡", verified="2019-01-01", urgent="y")]))
        code, out, _ = self.run_code(["brief", p, "--top", "1"])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("先用再信", out)

    def test_exit_lights_when_ledger_has_lights_outside_top(self):
        # 家属卡只取 top1,但账本别处的灯也要让 exit 4——交接时知道全貌有暗角
        p = self.ledger(six([row("新卡", verified="2026-09-01"),
                             row("老基金", cat="invest", verified="2019-01-01")]))
        code, _, _ = self.run_code(["brief", p, "--top", "1"])
        self.assertEqual(code, handoff.EXIT_LIGHTS)


class TestWho(Base):
    def test_knows_account_sums_to_items(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["who", p])
        self.assertIn("Σ各知情人件数 = 6 ≡ 条目数 6", out)
        self.assertIn("没有信息单点故障", out)

    def test_solo_ticket(self):
        rows = [row("工资卡", knows="spouse"),
                row("基金", cat="invest", knows="self-only"),
                row("旧邮箱", cat="digital", knows="self-only")]
        p = self.ledger(full_ledger(rows))
        code, out, _ = self.run_code(["who", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("self-only", out)
        self.assertIn("基金", out)
        self.assertIn("旧邮箱", out)
        self.assertIn("信息单点故障", out)

    def test_all_knows_buckets_listed(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["who", p])
        for k in handoff.KNOWS:
            self.assertIn(k, out)


class TestValidate(Base):
    def test_clean_ledger_all_identities_hold(self):
        p = self.ledger(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["validate", p])
        self.assertEqual(out.count("✓"), 5)
        self.assertNotIn("✗", out)
        self.assertIn("双路径重放", out)
        self.assertIn("交接卡回溯", out)
        self.assertIn("mask∘mask=mask", out)

    def test_validate_exit_zero_even_with_lights(self):
        # 体检只管账坏/恒等式,不因灯亮失败——灯是 report 的管辖
        p = self.ledger(full_ledger([row("老基金", cat="invest",
                                         verified="2019-01-01")]))
        code, out, _ = self.run_code(["validate", p])
        self.assertEqual(code, handoff.EXIT_OK)
        self.assertIn("账面带灯", out)

    def test_checked_count_reported(self):
        text = full_ledger(CLEAN_ROWS).replace(
            "# checked: 2026-09-06",
            "# checked: 2024-02-10\n# checked: 2026-09-06")
        p = self.ledger(text)
        out = self.run_ok(["validate", p])
        self.assertIn("盘点日声明 2 次(最后 2026-09-06)", out)


class TestTimeMachine(Base):
    # 六类齐全的老李小账:两行 verified 晚于时间机器锚点
    DEMO = """\
# 老李
# checked: 2024-02-10
# checked: 2026-09-06
""" + HDR + "".join([
        row("工行卡", cat="bank", verified="2026-09-06"),
        row("基金", cat="invest", knows="self-only", verified="2021-11-02"),
        row("重疾险", cat="policy", verified="2024-02-10"),
        row("房产证", cat="deed", verified="2026-09-06"),
        row("借条(别人欠我)", cat="debt", verified="2026-09-06"),
        row("旧邮箱", cat="digital", knows="self-only", where="", clue="",
            verified="2022-05-01"),
    ])

    def test_default_asof_is_last_checked(self):
        p = self.ledger(self.DEMO)
        code, out, _ = self.run_code(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)  # 基金/旧邮箱 STALE
        self.assertIn("as-of: 2026-09-06(# checked: 盘点日)", out)

    def test_rewound_view_has_fewer_stale(self):
        p = self.ledger(self.DEMO)
        code, out, _ = self.run_code(["report", p, "--as-of", "2024-02-10"])
        # 2024-02-10 视角:基金 STALE(830 天);重疾险恰当天不亮;旧邮箱还新鲜
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        self.assertIn("830 天", out)
        self.assertIn("SOLO NO-TRACE", out)   # 旧邮箱:时间变了灯的组合也变
        self.assertNotIn("939 天", out)       # 重疾险还没变旧
        self.assertIn("as-of: 2024-02-10(--as-of 钉死)", out)

    def test_list_never_hidden_by_time_machine(self):
        # 状态表整体呈现:条目计数与六类矩阵不因 as-of 变化——
        # 时间机器翻的是灯,不是清单
        p = self.ledger(self.DEMO)
        _, out_now, _ = self.run_code(["report", p])
        _, out_past, _ = self.run_code(["report", p, "--as-of", "2024-02-10"])
        self.assertIn("6 件", out_now)
        self.assertIn("6 件", out_past)
        for cat in handoff.CATEGORIES:
            zh = handoff.CATEGORIES[cat]
            self.assertIn(zh, out_now)
            self.assertIn(zh, out_past)
        # 带灯清单按当时的灯亮:重疾险只在「现在」的灯区出现
        self.assertIn("重疾险", out_now)
        self.assertNotIn("939 天", out_past)


class TestZeroWallClock(Base):
    def test_source_has_no_system_clock(self):
        with open(CLI, encoding="utf-8") as f:
            src = f.read()
        for bad in ("date.today", "datetime.now", "utcnow", "time.time",
                    "time.localtime", "time.gmtime"):
            self.assertNotIn(bad, src)

    def test_report_prints_basename_only(self):
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        p = os.path.join(sub, "handoff.tsv")
        with open(p, "w", encoding="utf-8") as f:
            f.write(full_ledger(CLEAN_ROWS))
        out = self.run_ok(["report", p])
        self.assertIn("handoff.tsv", out)
        self.assertNotIn(self.dir, out)
        self.assertNotIn("sub", out)

    def test_deterministic_same_ledger_same_bytes(self):
        p1 = self.ledger(full_ledger(CLEAN_ROWS), name="a.tsv")
        p2 = self.ledger(full_ledger(CLEAN_ROWS), name="b.tsv")
        outs = []
        for p in (p1, p2):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run(["report", p])
            outs.append(buf.getvalue())
        # 同账不同文件名只允许 basename 一行不同
        a, b = outs
        a = a.replace("a.tsv", "X").replace("X", "")
        b = b.replace("b.tsv", "X").replace("X", "")
        self.assertEqual(a, b)


class TestExamples(unittest.TestCase):
    """样例与快照:字节级可复现(CI 同款)。"""

    @unittest.skipUnless(os.path.isdir(EX_DIR), "examples missing")
    def test_build_check_byte_exact(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(EX_DIR, "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    @unittest.skipUnless(os.path.isdir(EX_DIR), "examples missing")
    def test_demo_story_lamps(self):
        p = os.path.join(EX_DIR, "handoff.tsv")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run(["report", p])
        self.assertEqual(code, handoff.EXIT_LIGHTS)
        text = out.getvalue()
        self.assertIn("11 件", text)
        self.assertIn("带灯 3", text)
        self.assertIn("debt 债权与债务", text)
        self.assertIn("1,769 天", text)   # 基金账户 2021-11-02
        self.assertIn("939 天", text)     # 重疾险 2024-02-10
        self.assertIn("1,589 天", text)   # 旧邮箱 2022-05-01
        self.assertIn("借出去的钱、欠别人的账", text)  # 盲区反问替他说出那句话


if __name__ == "__main__":
    unittest.main()
