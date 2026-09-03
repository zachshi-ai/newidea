# -*- coding: utf-8 -*-
"""A10 验收：dogfood —— 示例日志埋入已知答案，工具必须挖出来。

boombust.tsv 的故事线（见 examples/build_examples.py 模块注释）：
  第 1–8 周稳定打底（前三周基线校准中）→ 第 9 周比赛上头 →
  第 10 周（07/06–07/12）爆缸（ACWR≈1.8）→ 疼痛减量 → 伤停 15 天 →
  归队爬坡（判据冻结）。
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redline import build_report, daily_loads, parse_session_file, main

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.abspath(os.path.join(HERE, "..", "examples"))
BOOM = os.path.join(EXAMPLES, "boombust.tsv")
BOOM_MONDAY = date(2026, 7, 6)          # 埋入的爆缸周

# 与 build_examples.py 相同的数据源：exec 到临时目录即可重建示例
BUILD_SOURCE = open(os.path.join(EXAMPLES, "build_examples.py"),
                    encoding="utf-8").read()


def load_report():
    sessions, warnings = parse_session_file(BOOM)
    return build_report(daily_loads(sessions), warnings=warnings), sessions


class TestDogfood(unittest.TestCase):
    def setUp(self):
        self.rep, self.sessions = load_report()

    def test_boom_week_is_red_flagged(self):
        reds = [w for w in self.rep["weeks"] if w["zone"] == "red"]
        self.assertEqual(len(reds), 1, "恰好埋入一个爆缸周")
        self.assertEqual(reds[0]["monday"], BOOM_MONDAY)
        self.assertGreater(reds[0]["acwr"], 1.5)
        flags = [f for w in self.rep["weeks"] for f in w["flags"]]
        self.assertTrue(any("红线" in f for f in flags))

    def test_base_weeks_all_green_after_calibration(self):
        # 第 4–9 周（05/25 起）：稳定打底必须全绿
        greens = [w for w in self.rep["weeks"]
                  if date(2026, 5, 25) <= w["monday"] <= date(2026, 6, 29)]
        self.assertEqual(len(greens), 6)
        for w in greens:
            self.assertEqual(w["zone"], "green",
                             "%s 应在甜区" % w["monday"])

    def test_first_three_weeks_uncalibrated(self):
        # 基线校准期内：不判区（?），但数字照常展示
        early = [w for w in self.rep["weeks"]
                 if w["monday"] < date(2026, 5, 25)]
        self.assertEqual(len(early), 3)
        for w in early:
            self.assertFalse(w["calibrated"])
            self.assertFalse(w["frozen"])

    def test_pain_week_blue(self):
        # 第 11 周（07/13）疼痛减量：跌进退训区
        pain = [w for w in self.rep["weeks"]
                if w["monday"] == date(2026, 7, 13)]
        self.assertEqual(pain[0]["zone"], "blue")

    def test_layoff_detected_with_exact_dates(self):
        self.assertEqual(len(self.rep["layoffs"]), 1)
        lo = self.rep["layoffs"][0]
        self.assertEqual(lo["last_active"], "2026-07-21")
        self.assertEqual(lo["returned"], "2026-08-06")
        self.assertEqual(lo["days"], 15)

    def test_rebuild_ladder_and_freeze(self):
        rb = self.rep["rebuild"]
        self.assertIsNotNone(rb)
        self.assertEqual([r["pct"] for r in rb["ladder"]],
                         [0.40, 0.60, 0.80, 1.00])
        self.assertEqual(rb["freeze_until"], "2026-09-02")
        # 归队后的周全部冻结（⏳），爆缸周之前的周不受影响
        post = [w for w in self.rep["weeks"]
                if w["monday"] >= date(2026, 8, 3)]
        self.assertTrue(post)
        for w in post:
            self.assertTrue(w["frozen"], "%s 应冻结" % w["monday"])
        boom = [w for w in self.rep["weeks"]
                if w["monday"] == BOOM_MONDAY][0]
        self.assertFalse(boom["frozen"])

    def test_render_contains_story(self):
        sessions, warnings = parse_session_file(BOOM)
        rep = build_report(daily_loads(sessions), warnings=warnings)
        import redline
        text = redline.render_report(rep)
        for needle in ("红线", "伤停", "归队", "重建期", "ACWR"):
            self.assertIn(needle, text)
        self.assertIn("空窗 15 天", text)

    def test_examples_are_byte_identical_to_generator(self):
        # 示例同步：把生成器 exec 到临时目录，输出必须与提交的文件逐字节一致
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "build_examples.py")
        shutil_copy = open(src, "w", encoding="utf-8")
        shutil_copy.write(BUILD_SOURCE)
        shutil_copy.close()
        namespace = {"__name__": "__main__", "__file__": src}
        with redirect_stdout(io.StringIO()):
            exec(compile(BUILD_SOURCE, src, "exec"), namespace)
        for name in ("boombust.tsv", "minimal.tsv"):
            with open(os.path.join(EXAMPLES, name), "rb") as f:
                committed = f.read()
            with open(os.path.join(tmp, name), "rb") as f:
                rebuilt = f.read()
            self.assertEqual(committed, rebuilt,
                             "%s 与生成器输出不一致，请重新生成" % name)

    def test_minimal_log_validates(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["validate", os.path.join(EXAMPLES, "minimal.tsv")])
        self.assertEqual(code, 0)
        self.assertIn("✓", out.getvalue())

    def test_report_cli_advisory_exit_zero(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["report", BOOM])
        self.assertEqual(code, 0)
        # 渲染文本里有爆缸周的红色旗帜
        self.assertIn("07/06–07/12", out.getvalue())
        self.assertIn("🔴", out.getvalue())

    def test_report_json_roundtrip(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["report", BOOM, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        reds = [w for w in data["weeks"] if w["zone"] == "red"]
        self.assertEqual(len(reds), 1)
        self.assertEqual(reds[0]["monday"], BOOM_MONDAY.isoformat())


if __name__ == "__main__":
    unittest.main()
