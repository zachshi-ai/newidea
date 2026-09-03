# -*- coding: utf-8 -*-
"""A11/A12 验收：CLI 行为、JSON、确定性。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redline
from redline import main

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "..", "examples")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def tmp_log(rows):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "log.tsv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("date\tactivity\tminutes\trpe\tnotes\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    return path


STEADY = [("2026-01-%02d" % d, "跑", 100, 5, "") for d in range(1, 29)]


class TestReportCli(unittest.TestCase):
    def test_report_exit_zero_and_sections(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main(["report", path])
        self.assertEqual(code, 0)
        for marker in ("【校准状态】", "【当前转速】", "【周表】", "【建议】"):
            self.assertIn(marker, out)
        self.assertIn("🟢", out)

    def test_report_json_valid_and_complete(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main(["report", path, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        for key in ("as_of", "first_day", "calibrated", "current", "weeks",
                    "layoffs", "rebuild", "warnings"):
            self.assertIn(key, data)
        self.assertIn("acwr", data["current"])
        self.assertGreaterEqual(len(data["weeks"]), 4)
        self.assertEqual(data["current"]["zone"], "green")

    def test_report_strict_exit_two_on_red_week(self):
        code, out, _ = run_main(["report", os.path.join(EXAMPLES, "boombust.tsv"),
                                 "--strict"])
        self.assertEqual(code, 2)

    def test_report_plain_exit_zero_on_boombust(self):
        # 报告是监控产物：默认永不失败（CI advisory 步骤依赖这一点）
        code, out, _ = run_main(["report", os.path.join(EXAMPLES, "boombust.tsv")])
        self.assertEqual(code, 0)

    def test_report_missing_file_errors(self):
        code, out, err = run_main(["report", "/nonexistent/log.tsv"])
        self.assertEqual(code, 1)
        self.assertIn("✗", err)

    def test_report_as_of_backdate(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main(["report", path, "--as-of", "2026-01-10"])
        self.assertEqual(code, 0)
        self.assertIn("2026-01-10", out)
        self.assertIn("未校准", out)

    def test_determinism_byte_identical(self):
        path = tmp_log(STEADY)
        _, out1, _ = run_main(["report", path])
        _, out2, _ = run_main(["report", path])
        self.assertEqual(out1, out2)
        _, j1, _ = run_main(["report", path, "--json"])
        _, j2, _ = run_main(["report", path, "--json"])
        self.assertEqual(j1, j2)


class TestValidateCli(unittest.TestCase):
    def test_validate_ok(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, 0)
        self.assertIn("✓", out)
        self.assertIn("总负荷", out)

    def test_validate_bad_header_exit_one(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "bad.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("day\tmins\n2026-01-01\t40\n")
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, 1)
        self.assertIn("✗", out)

    def test_validate_reports_warnings_but_exits_zero(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "warn.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date\tminutes\trpe\n")
            f.write("2026-01-01\t40\t5\n")
            f.write("垃圾行垃圾行\t垃圾\t垃圾\n")
        code, out, _ = run_main(["validate", path])
        self.assertEqual(code, 0)
        self.assertIn("警告", out)


class TestPlanCli(unittest.TestCase):
    def test_plan_green_flow(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main([
            "plan", path,
            "--session", "2026-01-29,50,4,轻松跑"])
        self.assertEqual(code, 0)
        self.assertIn("🟢", out)
        self.assertIn("余额", out)

    def test_plan_red_strict_exit_two(self):
        path = tmp_log(STEADY)
        # STEADY 日负荷 500：再砸 4000 → acute 7500 / chronic 4500 = 1.67 红
        code, out, _ = run_main([
            "plan", path,
            "--session", "2026-01-28,400,10,爆冲课",
            "--strict"])
        self.assertEqual(code, 2)
        self.assertIn("红线", out)

    def test_plan_json(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main([
            "plan", path, "--json",
            "--session", "2026-01-29,50,4"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("headroom", data)
        self.assertEqual(len(data["rows"]), 1)

    def test_plan_bad_session_spec_exit_one(self):
        path = tmp_log(STEADY)
        code, out, err = run_main([
            "plan", path, "--session", "不是日期,60,5"])
        self.assertEqual(code, 1)
        self.assertIn("✗", err)

    def test_plan_multiple_sessions_ordered(self):
        path = tmp_log(STEADY)
        code, out, _ = run_main([
            "plan", path,
            "--session", "2026-01-30,60,5",
            "--session", "2026-01-29,40,3"])
        self.assertEqual(code, 0)
        # 输出行按日期升序：01-29 在 01-30 前面
        self.assertLess(out.index("2026-01-29"), out.index("2026-01-30"))


class TestVersion(unittest.TestCase):
    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            run_main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
