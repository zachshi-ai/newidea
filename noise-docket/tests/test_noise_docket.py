#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声讨 · Noise Docket 验收测试。

验收标准全部转成自动化测试：样例账本（小陈 31 天噪音账）钉死全部关键数字，
合成账本钉死夜间/禁令口径边界、判级线可调、灯与薄账豁免、verify 前后窗
恒等式与判读、letter 事实清单、零锚定与无系统时钟。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import noise_docket as nd  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "events.tsv")
BUILDER = os.path.join(ROOT, "examples", "build_examples.py")

_TMP = []


def _tmpfile(rows, header=("date", "start", "mins", "source",
                           "strength", "rec", "note")):
    fd, path = tempfile.mkstemp(suffix=".tsv")
    os.close(fd)
    lines = ["\t".join(header)]
    for r in rows:
        lines.append("\t".join(str(c) for c in r))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    _TMP.append(path)
    return path


import atexit  # noqa: E402


@atexit.register
def _cleanup_tmp():
    for p in _TMP:
        try:
            os.unlink(p)
        except OSError:
            pass


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    code = None
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = nd.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
    return code, out.getvalue() + err.getvalue()


def span(days, start="2026-07-06"):
    """从 start 起第 days 天的日期串（days 从 1 计）。"""
    import datetime
    d0 = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:10]))
    d = d0 + datetime.timedelta(days=days - 1)
    return d.isoformat()


# ---------------------------------------------------------------- 样例：总量

class TestExampleTotals(unittest.TestCase):

    def test_report_totals_pinned(self):
        code, out = run(["report", EXAMPLE])
        self.assertEqual(code, 4)
        self.assertIn("事件 19 次", out)
        self.assertIn("有噪日 18/29（62.1%）", out)
        self.assertIn("累计 857 分钟（14 小时 17 分）", out)

    def test_report_source_identity(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("装修   8 次   535 分", out)
        self.assertIn("拖动   4 次   158 分", out)
        self.assertIn("脚步   5 次   112 分", out)
        self.assertIn("棋牌   1 次    40 分", out)
        self.assertIn("宠物   1 次    12 分", out)
        # 恒等式：Σ来源 = 535+158+112+40+12 = 857
        self.assertEqual(535 + 158 + 112 + 40 + 12, 857)

    def test_report_night_share(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("夜间（22:00-06:00）7 次 · 273 分钟 · 占 31.9%", out)

    def test_report_offhours_five(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("禁令时段装修 5 次", out)

    def test_report_max_single(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("最长单次 100 分钟（2026-07-13 10:05 装修）", out)


# ---------------------------------------------------------------- 样例：判级

class TestExampleGrade(unittest.TestCase):

    def test_report_grade_unbearable(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("近窗判级（2026-07-21 → 2026-08-03 · 14 天）", out)
        self.assertIn("近窗 10 次 · 338 分钟 · 夜间 4 次 · 禁令装修 2 次", out)
        self.assertIn("判级 UNBEARABLE", out)
        self.assertIn("累计 338 分钟 ≥ 300", out)

    def test_lamps_on_sample(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("● OFF-HOURS  近窗禁令时段装修 2 次（全史 5 次）", out)
        self.assertIn("○ LONG-NIGHT", out)
        self.assertNotIn("● LONG-NIGHT", out)

    def test_trend_improving(self):
        code, out = run(["report", EXAMPLE])
        self.assertIn("前半窗 259 分钟/6 次 → 后半窗 79 分钟/4 次 —— 回落中", out)

    def test_pattern_exit_and_pin(self):
        code, out = run(["pattern", EXAMPLE])
        self.assertEqual(code, 4)
        self.assertIn("09-12   7 次   472 分", out)
        self.assertIn("19-22   5 次   112 分", out)
        self.assertIn("22-24   7 次   273 分", out)

    def test_pattern_weekday(self):
        code, out = run(["pattern", EXAMPLE])
        self.assertIn("一   6 次   315 分", out)
        self.assertIn("日   0 次     0 分", out)

    def test_pattern_night_cross(self):
        code, out = run(["pattern", EXAMPLE])
        self.assertIn("夜间 拖动   4 次   158 分", out)
        self.assertIn("夜间 装修   2 次    75 分", out)
        self.assertIn("夜间 棋牌   1 次    40 分", out)

    def test_pattern_sampling_disclosure(self):
        code, out = run(["pattern", EXAMPLE])
        self.assertIn("── 在场抽样披露 ──", out)
        self.assertIn("白天事件系统性缺席", out)


# ---------------------------------------------------------------- 时间机器

class TestTimeMachine(unittest.TestCase):

    def test_default_asof_is_max_date_bytes(self):
        _, out_default = run(["report", EXAMPLE])
        _, out_explicit = run(["report", EXAMPLE, "--as-of", "2026-08-03"])
        self.assertEqual(out_default, out_explicit)
        self.assertIn("as-of 2026-08-03", out_default)

    def test_asof_0721_already_unbearable(self):
        code, out = run(["report", EXAMPLE, "--as-of", "2026-07-21"])
        self.assertEqual(code, 4)
        self.assertIn("近窗 9 次 · 538 分钟", out)
        self.assertIn("判级 UNBEARABLE", out)
        self.assertIn("● OFF-HOURS  近窗禁令时段装修 3 次（全史 3 次）", out)

    def test_asof_stable_trend(self):
        code, out = run(["report", EXAMPLE, "--as-of", "2026-07-21"])
        self.assertIn("前半窗 269 分钟/4 次 → 后半窗 269 分钟/5 次 —— 平稳", out)

    def test_asof_before_first_day(self):
        code, out = run(["report", EXAMPLE, "--as-of", "2026-07-01"])
        self.assertEqual(code, 3)
        self.assertIn("无账可放", out)

    def test_basename_only(self):
        code, out = run(["report", EXAMPLE])
        self.assertNotIn("/Users", out)
        self.assertNotIn("noise-docket/examples", out)
        self.assertIn("账本 events.tsv", out)

    def test_deterministic_rerun(self):
        _, out1 = run(["report", EXAMPLE])
        _, out2 = run(["report", EXAMPLE])
        self.assertEqual(out1, out2)


# ---------------------------------------------------------------- 口径边界

def _one(path_date, start, mins, source):
    return _tmpfile([(path_date, start, mins, source, "2", "-", "t")])


class TestNightBoundary(unittest.TestCase):

    def _night_of(self, path):
        code, out = run(["report", path])
        for ln in out.splitlines():
            if ln.startswith("夜间（22:00-06:00）"):
                return int(ln.split("）")[1].split("次")[0].strip())
        self.fail("夜间行缺失")

    def test_2200_is_night(self):
        p = _one("2026-07-06", "22:00", 10, "脚步")
        self.assertEqual(self._night_of(p), 1)

    def test_2159_not_night(self):
        p = _one("2026-07-06", "21:59", 10, "脚步")
        self.assertEqual(self._night_of(p), 0)

    def test_0559_is_night(self):
        p = _one("2026-07-06", "05:59", 10, "脚步")
        self.assertEqual(self._night_of(p), 1)

    def test_0600_not_night(self):
        p = _one("2026-07-06", "06:00", 10, "脚步")
        self.assertEqual(self._night_of(p), 0)

    def test_night_window_tunable(self):
        # --night-end 07:00 后，06:30 算夜间
        p = _one("2026-07-06", "06:30", 10, "脚步")
        code, out = run(["report", p, "--night-end", "07:00"])
        self.assertIn("夜间（22:00-07:00）1 次", out)


class TestOffHoursBoundary(unittest.TestCase):

    def _off(self, path, extra=()):
        code, out = run(["report", path] + list(extra))
        for ln in out.splitlines():
            if ln.startswith("禁令时段装修"):
                return int(ln.split("装修")[1].split("次")[0].strip())
        self.fail("禁令行缺失")

    # 2026-07-06 是周一（工作日）
    def test_workday_2000_exact_is_off(self):
        p = _one("2026-07-06", "20:00", 10, "装修")
        self.assertEqual(self._off(p), 1)

    def test_workday_1959_not_off(self):
        p = _one("2026-07-06", "19:59", 10, "装修")
        self.assertEqual(self._off(p), 0)

    def test_workday_noon_window(self):
        p = _one("2026-07-06", "12:00", 10, "装修")
        self.assertEqual(self._off(p), 1)
        p = _one("2026-07-06", "11:59", 10, "装修")
        self.assertEqual(self._off(p), 0)
        p = _one("2026-07-06", "13:59", 10, "装修")
        self.assertEqual(self._off(p), 1)
        p = _one("2026-07-06", "14:00", 10, "装修")
        self.assertEqual(self._off(p), 0)

    def test_workday_morning_edge(self):
        p = _one("2026-07-06", "07:59", 10, "装修")
        self.assertEqual(self._off(p), 1)
        p = _one("2026-07-06", "08:00", 10, "装修")
        self.assertEqual(self._off(p), 0)

    def test_saturday_allday(self):
        p = _one("2026-07-11", "09:40", 10, "装修")
        self.assertEqual(self._off(p), 1)
        p = _one("2026-07-11", "15:00", 10, "装修")
        self.assertEqual(self._off(p), 1)

    def test_holiday_param(self):
        p = _one("2026-10-01", "10:00", 10, "装修")
        self.assertEqual(self._off(p), 0)  # 周四工作日 10 点合法
        self.assertEqual(self._off(p, ["--holidays", "2026-10-01"]), 1)

    def test_rest_param(self):
        p = _one("2026-07-06", "10:00", 10, "装修")
        self.assertEqual(self._off(p, ["--rest", "mon"]), 1)

    def test_renovation_only(self):
        # 禁令只对装修类生效：周六上午的脚步不是禁令问题
        p = _one("2026-07-11", "09:40", 10, "脚步")
        self.assertEqual(self._off(p), 0)


# ---------------------------------------------------------------- 灯与薄账

class TestLampsAndThin(unittest.TestCase):

    def test_offhours_lamp_exit4(self):
        p = _one("2026-07-11", "09:40", 60, "装修")
        code, out = run(["report", p])
        self.assertEqual(code, 4)
        self.assertIn("● OFF-HOURS", out)

    def test_offhours_lamp_disabled(self):
        p = _one("2026-07-11", "09:40", 60, "装修")
        code, out = run(["report", p, "--legal-line", "0"])
        self.assertEqual(code, 3)  # 灯关 + 薄账 → DECLINE
        self.assertIn("OFF-HOURS 灯已用 --legal-line 0 关闭", out)

    def test_longnight_lamp_overrides_thin(self):
        p = _tmpfile([
            (span(1), "14:00", 20, "脚步", "2", "-", "t"),
            (span(3), "23:10", 120, "装修", "5", "Y", "凌晨电钻"),
        ])
        code, out = run(["report", p])
        self.assertEqual(code, 4)
        self.assertIn("● LONG-NIGHT", out)
        self.assertIn("DECLINE", out)

    def test_thin_decline_exit3(self):
        p = _one("2026-07-06", "14:00", 20, "脚步")
        code, out = run(["report", p])
        self.assertEqual(code, 3)
        self.assertIn("判级 DECLINE", out)
        self.assertIn("事件 1 次", out)  # 算术照出
        self.assertIn("覆盖 1 天 < 14 天", out)


# ---------------------------------------------------------------- 判级线

def _span14(rows):
    """覆盖 14 天的合成账本（首日到第 14 天）。"""
    return _tmpfile(rows)


class TestGradeLines(unittest.TestCase):

    def test_unbearable_line_tunable(self):
        code, out = run(["report", EXAMPLE, "--unbearable-line", "500"])
        self.assertEqual(code, 4)
        self.assertIn("判级 SEVERE", out)
        self.assertIn("近窗夜间 4 次 ≥ 3", out)

    def test_night_line_tunable(self):
        code, out = run(["report", EXAMPLE, "--night-line", "10",
                         "--unbearable-line", "500"])
        self.assertEqual(code, 4)
        self.assertIn("判级 SEVERE", out)
        self.assertIn("近窗累计 338 分钟 ≥ 180", out)

    def test_quiet_notable_boundary(self):
        # 前 11 天每天 1 分钟垫足覆盖（在 3 天窗外），窗口内只有末尾这一件事
        filler = [(span(i), "15:00", 1, "脚步", "1", "-", "t")
                  for i in range(1, 12)]
        p59 = _span14(filler + [(span(14), "15:00", 59, "脚步", "2", "-", "t")])
        code, out = run(["report", p59, "--window", "3"])
        self.assertEqual(code, 0)
        self.assertIn("判级 QUIET", out)
        p60 = _span14(filler + [(span(14), "15:00", 60, "脚步", "2", "-", "t")])
        code, out = run(["report", p60, "--window", "3"])
        self.assertEqual(code, 0)
        self.assertIn("判级 NOTABLE", out)

    def test_unbearable_night_channel(self):
        rows = [(span(i), "22:30", 10, "脚步", "3", "-", "夜")
                for i in range(1, 6)]
        p = _span14(rows)
        code, out = run(["report", p, "--as-of", span(14)])
        self.assertEqual(code, 4)
        self.assertIn("判级 UNBEARABLE", out)
        self.assertIn("夜间 5 次 ≥ 5", out)

    def test_unbearable_mins_channel(self):
        rows = [(span(d), "15:00", 80, "脚步", "2", "-", "t")
                for d in (1, 4, 7, 10)]
        p = _span14(rows)
        code, out = run(["report", p, "--as-of", span(14)])
        self.assertEqual(code, 4)
        self.assertIn("判级 UNBEARABLE", out)
        self.assertIn("累计 320 分钟 ≥ 300", out)


# ---------------------------------------------------------------- verify

class TestVerify(unittest.TestCase):

    def test_verify_pinned_improved(self):
        code, out = run(["verify", EXAMPLE, "--since", "2026-08-01",
                         "--label", "物业调解+隔音垫"])
        self.assertEqual(code, 0)
        self.assertIn("前窗 2026-07-06 → 2026-07-31（26 天）：17 次 · 830 分钟"
                      " · 夜间 7 次 · 31.9 分/天", out)
        self.assertIn("后窗 2026-08-01 → 2026-08-03（3 天）：2 次 · 27 分钟"
                      " · 夜间 0 次 · 9.0 分/天", out)
        self.assertIn("恒等式：前窗 + 后窗 = 全史（次数/分钟/夜间）——通过（残差 0）",
                      out)
        self.assertIn("变化 71.8%", out)
        self.assertIn("夜间从 7 次降到 0 次", out)
        self.assertIn("判读 IMPROVED", out)

    def test_verify_label_display(self):
        code, out = run(["verify", EXAMPLE, "--since", "2026-08-01",
                         "--label", "物业调解+隔音垫"])
        self.assertIn("标记日 2026-08-01（物业调解+隔音垫）", out)

    def test_verify_thin_back_window(self):
        code, out = run(["verify", EXAMPLE, "--since", "2026-08-03"])
        self.assertEqual(code, 0)
        self.assertIn("薄账提示：后窗仅 1 次", out)
        self.assertIn("变化 50.1%", out)

    def test_verify_front_empty(self):
        code, out = run(["verify", EXAMPLE, "--since", "2026-07-01"])
        self.assertEqual(code, 3)
        self.assertIn("标记日之前没有记录", out)

    def test_verify_worse(self):
        p = _span14([
            (span(2), "15:00", 10, "脚步", "2", "-", "t"),
            (span(8), "15:00", 100, "脚步", "4", "-", "t"),
            (span(9), "15:00", 100, "脚步", "4", "-", "t"),
        ])
        code, out = run(["verify", p, "--since", span(8)])
        self.assertEqual(code, 4)
        self.assertIn("判读 WORSE", out)
        self.assertIn("拿这页数字去升级", out)

    def test_verify_unchanged(self):
        p = _span14([
            (span(2), "15:00", 70, "脚步", "2", "-", "t"),
            (span(9), "15:00", 70, "脚步", "2", "-", "t"),
        ])
        code, out = run(["verify", p, "--since", span(8), "--as-of", span(14)])
        self.assertEqual(code, 0)
        self.assertIn("判读 UNCHANGED", out)
        self.assertIn("变化在噪声里", out)


# ---------------------------------------------------------------- letter

class TestLetter(unittest.TestCase):

    def setUp(self):
        self.code, self.out = run(["letter", EXAMPLE])

    def test_letter_pinned(self):
        self.assertIn("记录总数：19 次，累计 857 分钟（14 小时 17 分）", self.out)
        self.assertIn("夜间（22:00-06:00）记录：7 次，占 36.8%", self.out)
        self.assertIn("单次最长：100 分钟（2026-07-13 10:05，装修）", self.out)
        self.assertIn("- 装修：8 次（535 分钟）", self.out)
        self.assertIn("29 天，其中 18 天有噪声记录", self.out)

    def test_letter_offhours_rows(self):
        self.assertIn("- 2026-07-11（周六 09:40）装修 95 分钟——法定禁止时段",
                      self.out)
        self.assertIn("- 2026-07-24（周五 22:05）装修 40 分钟——法定禁止时段",
                      self.out)
        self.assertEqual(self.out.count("法定禁止时段"), 5)

    def test_letter_rec_marks(self):
        self.assertIn("2. 2026-07-11 09:40 装修 95 分钟 [有录音/录像]", self.out)
        self.assertEqual(self.out.count("[有录音/录像]"), 3)

    def test_letter_no_strength(self):
        # 主观强度不上信：信里只出现日期/时刻/时长/来源
        self.assertNotIn("强度", self.out)

    def test_letter_disclaimer(self):
        self.assertIn("以上内容仅陈述个人记录到的事实，不含主观评价", self.out)
        self.assertIn("诉求另行当面沟通", self.out)

    def test_letter_exit_follows_grade(self):
        self.assertEqual(self.code, 4)

    def test_letter_to_param(self):
        code, out = run(["letter", EXAMPLE, "--to", "社区居民委员会"])
        self.assertIn("致：社区居民委员会", out)


# ---------------------------------------------------------------- 别名归一

class TestAliases(unittest.TestCase):

    def test_alias_aggregate(self):
        p = _tmpfile([
            (span(1), "10:00", 10, "电钻", "3", "-", "t"),
            (span(3), "10:00", 10, "装修", "3", "-", "t"),
            (span(5), "16:00", 10, "跑跳", "2", "-", "t"),
            (span(7), "16:00", 10, "麻将", "3", "-", "t"),
        ])
        code, out = run(["report", p])
        self.assertIn("装修   2 次", out)
        self.assertIn("脚步   1 次", out)
        self.assertIn("棋牌   1 次", out)

    def test_alias_table(self):
        for a, b in [("电钻", "装修"), ("跑跳", "脚步"), ("麻将", "棋牌"),
                     ("犬吠", "宠物"), ("renovation", "装修")]:
            self.assertEqual(nd.ALIASES[a], b)


# ---------------------------------------------------------------- validate

class TestValidate(unittest.TestCase):

    def test_validate_ok(self):
        code, out = run(["validate", EXAMPLE])
        self.assertEqual(code, 0)
        self.assertIn("恒等式一（Σ来源 = 总分钟）：通过", out)
        self.assertIn("恒等式二（夜间 + 日间 = 总分钟）：通过（夜间 273 + 日间 584 = 857）",
                      out)
        self.assertIn("恒等式三（近窗 2026-07-21 → 2026-08-03 双算法：集合过滤 == "
                      "逐日游走）：通过（338 == 338）", out)
        self.assertIn("账本体检通过", out)

    def test_validate_cross_midnight(self):
        code, out = run(["validate", EXAMPLE])
        self.assertIn("跨午夜事件 2 次", out)
        self.assertIn("2026-07-15 23:50 30 分钟 → 结束于次日 00:20", out)

    def test_validate_bad_mins(self):
        p = _tmpfile([("2026-07-06", "10:00", 0, "脚步", "2", "-", "t")])
        code, out = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("时长必须为正整数分钟", out)

    def test_validate_negative_mins(self):
        p = _tmpfile([("2026-07-06", "10:00", -5, "脚步", "2", "-", "t")])
        code, _ = run(["validate", p])
        self.assertEqual(code, 2)

    def test_validate_bad_start(self):
        p = _tmpfile([("2026-07-06", "24:30", 10, "脚步", "2", "-", "t")])
        code, out = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("时刻越界", out)

    def test_validate_bad_source(self):
        p = _tmpfile([("2026-07-06", "10:00", 10, "抖腿", "2", "-", "t")])
        code, out = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("未知噪声来源", out)

    def test_validate_bad_date(self):
        p = _tmpfile([("2026/07/06", "10:00", 10, "脚步", "2", "-", "t")])
        code, out = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("日期无法解析", out)

    def test_validate_overlap_warns_not_fails(self):
        p = _tmpfile([
            (span(1), "10:00", 30, "装修", "3", "-", "t"),
            (span(1), "10:20", 30, "装修", "3", "-", "t"),
        ])
        code, out = run(["validate", p])
        self.assertEqual(code, 0)
        self.assertIn("时间重叠", out)
        self.assertIn("账本体检通过（1 条警告）", out)

    def test_validate_empty(self):
        p = _tmpfile([])
        code, out = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("账本为空", out)


# ---------------------------------------------------------------- 零锚定

class TestZeroAnchor(unittest.TestCase):

    def test_no_wall_clock_in_source(self):
        with open(os.path.join(ROOT, "noise_docket.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for banned in ("datetime.now", ".today()", "import time", "utcnow",
                       "date.today", "localtime", "gmtime"):
            self.assertNotIn(banned, src)

    def test_examples_bytes_stable(self):
        r = subprocess.run(
            [sys.executable, BUILDER, "--check"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("byte-exact", r.stdout)


if __name__ == "__main__":
    unittest.main()
