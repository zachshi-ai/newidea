# -*- coding: utf-8 -*-
"""A1 验收：日志解析。"""
import os
import tempfile
import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redline
from redline import LogError, parse_session_file, daily_loads


def write_log(rows, header="date\tactivity\tminutes\trpe\tnotes",
              name="log.tsv", content=None):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        if content is not None:
            f.write(content)
            return path
        f.write(header + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    return path


class TestParsing(unittest.TestCase):
    def test_basic_parse_and_load(self):
        path = write_log([("2026-03-01", "轻松跑", 40, 4, "热身"),
                          ("2026-03-02", "间歇课", 50, 8, "")])
        sessions, warnings = parse_session_file(path)
        self.assertEqual(warnings, [])
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["load"], 160.0)
        self.assertEqual(sessions[1]["load"], 400.0)

    def test_column_order_free(self):
        path = write_log([("轻松跑", "2026-03-01", 4, 40)],
                         header="activity\tdate\trpe\tminutes")
        sessions, _ = parse_session_file(path)
        self.assertEqual(sessions[0]["minutes"], 40.0)
        self.assertEqual(sessions[0]["load"], 160.0)

    def test_optional_columns_absent(self):
        path = write_log([("2026-03-01", 40, 5)],
                         header="date\tminutes\trpe")
        sessions, warnings = parse_session_file(path)
        self.assertEqual(warnings, [])
        self.assertEqual(sessions[0]["activity"], "训练")  # 默认名
        self.assertEqual(sessions[0]["load"], 200.0)

    def test_comments_and_blank_lines_skipped(self):
        path = write_log(None, content=(
            "# 我的训练日志\n"
            "\n"
            "date\tactivity\tminutes\trpe\tnotes\n"
            "# 下面是数据\n"
            "2026-03-01\t轻松跑\t40\t4\t\n"
            "\n"
            "2026-03-02\t节奏跑\t30\t6\t\n"))
        sessions, warnings = parse_session_file(path)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(warnings, [])

    def test_bad_rows_collected_with_line_numbers(self):
        path = write_log(None, content=(
            "date\tactivity\tminutes\trpe\tnotes\n"
            "2026-03-01\t轻松跑\t40\t4\t\n"
            "not-a-date\t轻松跑\t40\t4\t\n"
            "2026-03-02\t轻松跑\tabc\t4\t\n"
            "2026-03-03\t轻松跑\t40\t11\t\n"
            "2026-03-04\t轻松跑\t-5\t4\t\n"
            "2026-03-05\n"))
        sessions, warnings = parse_session_file(path)
        self.assertEqual(len(sessions), 1)          # 只有第一行可用
        self.assertEqual(len(warnings), 5)          # 坏行一次报全
        self.assertIn("第 3 行", warnings[0])
        self.assertIn("ISO", warnings[0])
        self.assertIn("第 4 行", warnings[1])
        self.assertIn("第 5 行", warnings[2])
        self.assertIn("0–10", warnings[2])
        self.assertIn("第 6 行", warnings[3])
        self.assertIn("第 7 行", warnings[4])

    def test_zero_load_rows_skipped_with_warning(self):
        path = write_log([("2026-03-01", "休息", 0, 0, "完全休息")])
        with self.assertRaises(LogError) as ctx:
            parse_session_file(path)
        self.assertIn("1 条警告", str(ctx.exception))

    def test_zero_load_row_among_good_rows_warns_only(self):
        path = write_log([("2026-03-01", "休息", 0, 0, "完全休息"),
                          ("2026-03-02", "轻松跑", 40, 4, "")])
        sessions, warnings = parse_session_file(path)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("不产生负荷", warnings[0])

    def test_rows_sorted_by_date(self):
        path = write_log([("2026-03-03", "a", 30, 5, ""),
                          ("2026-03-01", "c", 30, 5, ""),
                          ("2026-03-02", "b", 30, 5, "")])
        sessions, _ = parse_session_file(path)
        self.assertEqual([s["date"].day for s in sessions], [1, 2, 3])

    def test_csv_comma_also_accepted(self):
        path = write_log(None, content=(
            "date,activity,minutes,rpe,notes\n"
            "2026-03-01,轻松跑,40,4,\n"))
        sessions, warnings = parse_session_file(path)
        self.assertEqual(warnings, [])
        self.assertEqual(sessions[0]["load"], 160.0)

    def test_missing_required_header_raises(self):
        path = write_log([("2026-03-01", "轻松跑", 40)],
                         header="date\tactivity\tminutes")
        with self.assertRaises(LogError) as ctx:
            parse_session_file(path)
        self.assertIn("rpe", str(ctx.exception))

    def test_empty_file_raises(self):
        path = write_log(None, content="")
        with self.assertRaises(LogError):
            parse_session_file(path)

    def test_all_bad_rows_raises(self):
        path = write_log(None, content=(
            "date\tminutes\trpe\n"
            "垃圾\t垃圾\t垃圾\n"))
        with self.assertRaises(LogError) as ctx:
            parse_session_file(path)
        self.assertIn("没有可用会话", str(ctx.exception))

    def test_same_day_doubles_aggregate(self):
        path = write_log([("2026-03-01", "晨跑", 40, 4, ""),
                          ("2026-03-01", "夜跑", 30, 5, "")])
        sessions, _ = parse_session_file(path)
        daily = daily_loads(sessions)
        self.assertAlmostEqual(daily[sessions[0]["date"]], 160.0 + 150.0)

    def test_missing_notes_column_tolerated(self):
        path = write_log(None, content=(
            "date\tactivity\tminutes\trpe\n"
            "2026-03-01\t轻松跑\t40\t4\n"))
        sessions, warnings = parse_session_file(path)
        self.assertEqual(warnings, [])
        self.assertEqual(sessions[0]["notes"], "")

    def test_rpe_accepts_float(self):
        path = write_log([("2026-03-01", "轻松跑", 40, 4.5, "")])
        sessions, _ = parse_session_file(path)
        self.assertAlmostEqual(sessions[0]["load"], 180.0)


if __name__ == "__main__":
    unittest.main()
