# -*- coding: utf-8 -*-
"""owed-word · 应承 验收测试.

验收标准(README 承诺的全部转成自动化测试):
  解析层    中文状态归一(办了/办不了/收回/悬着)/缺右列视为空/行尾制表符
            容忍/注释行/6 列拒/缺表头拒/未知状态拒/缺 who/缺 what=没法结案/
            缺日期/日期不补零/假日期/due 坏日期/done 坏日期/结案日早于答应日
            拒/期限早于答应日拒/同人同事同日重复拒/空账 exit 3/缺文件 exit 2
  判灯恰线  due 当天 OVERDUE(宽容为零)/due 前一天 OK/悬龄第 14 天 OK/
            第 15 天 AGING 恰亮/第 30 天仍 AGING/第 31 天 STALE/
            有 due 的行期限内不按悬龄吵/结案三态不亮灯/declined 是已结的账
  命令      report 样例灯统计/人排行(阿岚 2 件)/全绿 clean exit 0/
            时间机器剪后视行+披露(当时大鹏恰亮 AGING、小舟还没过期)/
            缺省锚定最大答应日+披露/next 排序(期限债→悬账降龄→预警)/
            settled 拒绝占比+办结周期/validate 恒等式+重放+open 带 done 拒
  通用      basename only/同账两跑逐字节一致/仓库根目录跑法绝对路径
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EX_WORDS = os.path.join(ROOT, "examples", "words.tsv")
EX_CLEAN = os.path.join(ROOT, "examples", "clean.tsv")
sys.path.insert(0, ROOT)
import owed_word  # noqa: E402

AS_OF = "2026-02-10"


def run(argv):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = owed_word.main(argv)
    return code, buf.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tsv(self, content, name="w.tsv"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    HEADER = "who\twhat\tdate\tstate\tnote\n"

    def led(self, content=None, name="w.tsv"):
        return self.tsv(self.HEADER + (content or ""), name)


class TestParse(Base):
    def test_state_alias_cn(self):
        cases = {"办了": "did", "已办": "did", "办不了": "declined",
                 "婉拒": "declined", "收回": "returned", "悬着": "open",
                 "不用了": "returned"}
        for raw, want in cases.items():
            self.assertEqual(owed_word.norm_state(raw), want, raw)

    def test_state_unknown_refused(self):
        with self.assertRaises(ValueError):
            owed_word.norm_state("想想办法")

    def test_missing_right_cols_tolerated(self):
        p = self.led("老唐\t带绘本\t2025-11-02\n")  # 3 列,右缺视为空
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_trailing_tab_tolerated(self):
        p = self.led("老唐\t带绘本\t2025-11-02\tdeclined\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_comment_and_blank_skipped(self):
        p = self.tsv("# 老蒋的应承账\n\n" + self.HEADER +
                     "老唐\t带绘本\t2025-11-02\tdid\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_six_cols_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\tdid\tx\textra\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("6 > 5", err)

    def test_no_header_refused(self):
        p = self.tsv("老唐\t带绘本\t2025-11-02\tdid\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("表头", err)

    def test_unknown_state_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\t想想办法\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("未知状态", err)

    def test_no_who_refused(self):
        p = self.led("\t带绘本\t2025-11-02\topen\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("who", err)

    def test_no_what_refused(self):
        # 「帮忙」没法结案:what 是验收的刻度
        p = self.led("老唐\t\t2025-11-02\topen\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("能验收", err)

    def test_no_date_refused(self):
        p = self.led("老唐\t带绘本\t\topen\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)

    def test_date_not_zeropadded_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-2\topen\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("补零", err)

    def test_fake_date_refused(self):
        p = self.led("老唐\t带绘本\t2025-02-30\topen\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("真实存在", err)

    def test_bad_due_in_note_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\topen\tdue:2025-13-01\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("due日", err)

    def test_done_free_text_tolerated(self):
        # note 是自由文本:不像日期的 done: 当随手记容忍(宽进),
        # 长得像日期的(如 done:2025-13-01)才按日期验证拒绝
        p = self.led("老唐\t带绘本\t2025-11-02\tdid\tdone:上周日带到\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_done_before_promise_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\tdid\tdone:2025-11-01\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("时间倒转", err)

    def test_due_before_promise_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\topen\tdue:2025-11-01\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("交不了卷", err)

    def test_dup_row_refused(self):
        row = "老唐\t带绘本\t2025-11-02\topen\t\n"
        p = self.led(row + row)
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("重复", err)

    def test_empty_ledger_exit3(self):
        p = self.led("")
        code, _, err = run(["report", p, "--as-of", AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("空账", err)

    def test_comment_only_is_empty_exit3(self):
        p = self.tsv("# 只有注释\n")
        code, _, err = run(["report", p, "--as-of", AS_OF])
        self.assertEqual(code, 3)

    def test_missing_file_exit2(self):
        code, _, _ = run(["report", os.path.join(self.tmp, "nope.tsv")])
        self.assertEqual(code, 2)


class TestJudge(Base):
    def judge(self, content, as_of):
        p = self.led(content)
        entries = owed_word.parse_tsv(p)
        return owed_word.judge(entries[0], owed_word.parse_date(as_of))

    def test_due_day_exact_overdue(self):
        st = self.judge("阿岚\t给意见\t2026-02-09\topen\tdue:2026-02-10\n", AS_OF)
        self.assertEqual(st, "OVERDUE")  # 恰线即亮,宽容为零

    def test_day_before_due_ok(self):
        st = self.judge("阿岚\t给意见\t2026-02-09\topen\tdue:2026-02-11\n", AS_OF)
        self.assertEqual(st, "OK")

    def test_aging_exactly_15(self):
        st = self.judge("阿岚\t给意见\t2026-01-26\topen\t\n", AS_OF)  # 悬 15 天
        self.assertEqual(st, "AGING")

    def test_day14_ok(self):
        st = self.judge("阿岚\t给意见\t2026-01-27\topen\t\n", AS_OF)  # 悬 14 天
        self.assertEqual(st, "OK")

    def test_day30_still_aging(self):
        st = self.judge("阿岚\t给意见\t2026-01-11\topen\t\n", AS_OF)  # 悬 30 天
        self.assertEqual(st, "AGING")

    def test_day31_stale(self):
        st = self.judge("阿岚\t给意见\t2026-01-10\topen\t\n", AS_OF)  # 悬 31 天
        self.assertEqual(st, "STALE")

    def test_due_in_future_not_judged_by_age(self):
        # 期限内外是正常等待:答应再久,due 未到就不吵
        st = self.judge("阿岚\t给意见\t2025-08-01\topen\tdue:2026-05-01\n", AS_OF)
        self.assertEqual(st, "OK")

    def test_settled_never_lit(self):
        for st in ("did", "declined", "returned"):
            s = self.judge(f"老唐\t带绘本\t2025-11-02\t{st}\t\n", AS_OF)
            self.assertEqual(s, "DONE", st)


class TestCommands(Base):
    def test_report_light_census(self):
        code, out, _ = run(["report", EX_WORDS, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("7 句应承 · 悬着 5(🔴2 🟡2) · 已结 2 · 未亮 1", out)
        self.assertIn("人排行", out)
        self.assertIn("同事阿岚 2 件", out)
        self.assertLess(out.index("同事阿岚 2 件"), out.index("老同学大鹏 1 件"))

    def test_declined_is_closed_clean(self):
        code, out, _ = run(["report", EX_WORDS, "--as-of", AS_OF])
        self.assertIn("说出口的「不」是已结的账", out)

    def test_clean_ledger_exit0(self):
        code, out, _ = run(["report", EX_CLEAN, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertNotIn("exit 4", out)

    def test_time_machine_clips_and_discloses(self):
        code, out, _ = run(["report", EX_WORDS, "--as-of", "2025-12-15"])
        self.assertEqual(code, 4)
        self.assertIn("剪掉 3 笔晚于 as-of 的后视行", out)
        self.assertIn("悬龄 15 天", out)       # 大鹏 AGING 恰亮
        self.assertIn("期限 2025-12-31 未到", out)  # 小舟当时还没过期
        self.assertNotIn("阿岚", out)           # 后视行被剪

    def test_default_anchors_max_date(self):
        code, out, _ = run(["report", EX_WORDS])
        self.assertEqual(code, 4)
        self.assertIn("未钉 as-of,缺省锚定账本最大答应日", out)
        self.assertIn("as-of 2026-02-01", out)  # 账本最大答应日(小陈)

    def test_next_order_and_exit(self):
        code, out, _ = run(["next", EX_WORDS, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        i_over = out.index("期限债")
        i_stale = out.index("悬账")
        i_aging = out.index("预警")
        self.assertLess(i_over, i_stale)
        self.assertLess(i_stale, i_aging)
        self.assertIn("4 句要回话(🔴2 🟡2)", out)

    def test_next_all_green(self):
        code, out, _ = run(["next", EX_CLEAN, "--as-of", AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("不用还嘴上的债", out)

    def test_settled_stats(self):
        code, out, _ = run(["settled", EX_WORDS, "--as-of", AS_OF])
        self.assertEqual(code, 4)  # 账面仍有悬灯
        self.assertIn("已结 2:办了 1 / 办不了 1 / 对方收回 0 · 拒绝占比 50.0%", out)
        self.assertIn("办结周期(有记结案日的 1 笔):最短 18 天", out)
        self.assertIn("健康指标,不是污点", out)

    def test_settled_no_done_rows(self):
        p = self.led("老唐\t带绘本\t2026-01-05\topen\t\n")
        code, out, _ = run(["settled", p, "--as-of", "2026-01-06"])
        self.assertIn("还没有结案", out)

    def test_validate_green_and_identity(self):
        code, out, _ = run(["validate", EX_WORDS])
        self.assertEqual(code, 0)
        self.assertIn("open 5 + did 1 + declined 1 + returned 0 = 7", out)
        self.assertIn("双路径重放逐行全等", out)

    def test_validate_open_with_done_refused(self):
        p = self.led("老唐\t带绘本\t2025-11-02\topen\tdone:2025-11-20\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        # open+done 在 report 也是账坏语义,validate 拒绝预写结局
        code2, _, _ = run(["report", p, "--as-of", AS_OF])
        self.assertEqual(code2, 4)  # report 层容忍并照常判灯,validate 层拒预写结局

    def test_line_number_backtrack(self):
        with open(EX_WORDS, encoding="utf-8") as f:
            lines = f.read().split("\n")
        code, out, _ = run(["next", EX_WORDS, "--as-of", AS_OF])
        self.assertIn("L4", out)
        self.assertIn("小舟", lines[3])  # L4 是表弟小舟行(1-based 含表头)


class TestGeneral(Base):
    def test_basename_only(self):
        code, out, _ = run(["report", EX_WORDS, "--as-of", AS_OF])
        self.assertNotIn("owed-word/examples", out)
        self.assertNotIn(os.getcwd(), out)

    def test_byte_identical_two_runs(self):
        a = run(["report", EX_WORDS, "--as-of", AS_OF])
        b = run(["report", EX_WORDS, "--as-of", AS_OF])
        self.assertEqual(a, b)

    def test_replay_matches_parse_layer(self):
        entries = owed_word.parse_tsv(EX_WORDS)
        replay = owed_word.replay_from_text(EX_WORDS)
        pa = [(e.who, e.what, e.date.isoformat(), e.state) for e in entries]
        self.assertEqual(pa, replay)

class TestCliAndEdge(Base):
    def test_state_blank_defaults_open(self):
        p = self.led("老唐\t带绘本\t2025-11-02\t\t\n")
        entries = owed_word.parse_tsv(p)
        self.assertEqual(entries[0].state, "open")

    def test_overdue_same_day_wording(self):
        # 恰线文案:「今天就是说过交卷的日子」只在过期 0 天出现
        p = self.led("阿岚\t给意见\t2026-01-05\topen\tdue:2026-02-10\n")
        code, out, _ = run(["report", p, "--as-of", AS_OF])
        self.assertIn("今天就是说过交卷的日子", out)
        self.assertNotIn("已过 0 天", out)

    def test_overdue_next_day_wording(self):
        p = self.led("阿岚\t给意见\t2026-01-05\topen\tdue:2026-02-09\n")
        code, out, _ = run(["report", p, "--as-of", AS_OF])
        self.assertIn("已过 1 天", out)

    def test_next_overdue_same_day_wording(self):
        p = self.led("阿岚\t给意见\t2026-01-05\topen\tdue:2026-02-10\n")
        code, out, _ = run(["next", p, "--as-of", AS_OF])
        self.assertIn("今晚之前,办掉或回话", out)

    def test_unknown_kv_in_note_tolerated(self):
        # note 自由文本:非 due:/done: 键值原样保留
        p = self.led("老唐\t带绘本\t2025-11-02\topen\t饭桌上说的,随便记一笔\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_validate_broken_ledger_exit2(self):
        p = self.led("老唐\t带绘本\t2025-02-30\topen\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 2)

    def test_settled_cycle_not_recorded_disclosed(self):
        p = self.led("老唐\t带绘本\t2025-11-02\tdid\t忘了记哪天结的\n")
        code, out, _ = run(["settled", p, "--as-of", AS_OF])
        self.assertIn("结案日未记(周期不计)", out)
        self.assertNotIn("平均", out)

    def test_what_free_text_with_punct(self):
        # 「改天聚聚」也该被悬龄点名——what 不设词表,验收刻度交给编辑纪律
        p = self.led("大鹏\t改天聚聚\t2025-11-30\topen\t\n")
        code, out, _ = run(["report", p, "--as-of", AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("STALE", out) if False else self.assertIn("🔴", out)

    def test_due_and_done_coexist(self):
        p = self.led("阿岚\t给意见\t2026-01-05\tdid\tdue:2026-01-20 done:2026-01-15\n")
        code, out, _ = run(["settled", p, "--as-of", AS_OF])
        self.assertIn("周期 10 天", out)

    def test_human_ranking_tie_by_name(self):
        p = self.led("乙某人\t事A\t2026-01-10\topen\t\n"
                     "甲某人\t事B\t2026-01-11\topen\t\n")
        code, out, _ = run(["report", p, "--as-of", AS_OF])
        # 同数按名字码位升序:乙(U+4E59) 在 甲(U+7532) 前
        self.assertLess(out.index("乙某人 1 件"), out.index("甲某人 1 件"))


if __name__ == "__main__":
    unittest.main()
