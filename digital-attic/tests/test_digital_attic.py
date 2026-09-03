#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digital-attic · 数字阁楼 — 验收测试.

验收标准（全部转成自动化测试）：
  A1  账本解析：坏行带行号 exit 2（列数/bytes 非整数或为负/birth 缺失或非法/
      出生在未来/source 非法/重复登记/账本缺失）
  A2  表头、注释行（#）与空行跳过
  A3  出生日期考古：13 种真实命名模式对表；无日期名返 None；
      数字串长得像日期但不是日期（20231332）返 None；
      IMG_20230521_202000 取 20230521（时间串 20 开头不抢先）
  A4  身份判定：screenshot（英/中/安卓/WX 前缀）、chat（微信图片/WeChat/WXIMG）、
      video 按扩展名；录屏 mp4（名字优先）归 screenshot
  A5  burst 全库互查：同目录+基名+同分钟 ≥3 成簇；2 张不成簇；
      连号不同分钟不成簇；跨目录不成簇
  A6  恒等式：五类身份件数/字节加总 = 总件数/总字节（demo 账本，残差 0）
  A7  双口径分裂（demo 钉死）：垃圾 646 件 50.7% 件数 vs 928 MB 0.3% 字节
  A8  库龄两把尺（demo 钉死）：按件 3.1 年 > 按字节 2.0 年——新的重，老的轻
  A9  出生来源（demo 钉死）：name 1,262 / mtime 12；增速行 +1.0% 匀速
  A10 门禁两把尺独立触发：垃圾件数 > 50% → RED exit 4（demo）；
      垃圾字节 > 30% 且件数未过半 → RED exit 4（构造账本）；干净账本 GREEN exit 0
  A11 THIN：账本 < 30 件 → census/pyramid/junk/rent/simulate 全线 exit 3
  A12 房租：单价 = price/quota 手算对表；视频租占比 99.1%（demo）；
      未给 --price/--quota 不发明单价；rent 缺参 argparse exit 2；
      库超档挂横幅
  A13 金字塔：2019-2026 共 8 行；条宽确定性归一
  A14 simulate：junk 口径 = 三匠之和（恒等式）；清空垃圾幸存库 GREEN；
      prune videos 大房东一走垃圾露馅（幸存库字节口径 RED）；
      simulate 永不 exit 4；aged --years 0 拒绝 exit 3；
      空口径 exit 3；aged 横幅「aged ≠ 该删」
  A15 scan：文件名日期 source=name；无日期名 source=mtime 且 birth= mtime；
      name 优先于 mtime；寄居户（非媒体）不入账披露；scan→census 闭环；
      零媒体/目录不存在 exit 3
  A16 --today 钉死逐字节可复现；库龄随 today 正确变化
  A17 validate：mtime 兜底 > 30% 挂警告；同名不同目录披露
  A18 隐私：报告不回显账本绝对路径
  A19 零依赖：只 import 标准库
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digital_attic as da  # noqa: E402

TODAY = "2026-09-01"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(BASE, "examples", "attic.tsv")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = da.main(list(argv))
        except SystemExit as e:      # argparse usage error
            code = e.code if isinstance(e.code, int) else 2
    return code, out.getvalue(), err.getvalue()


class LedgerTestCase(unittest.TestCase):
    """带临时目录与账本助手的基类。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="attic.tsv"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def pad_rows(self, n=30, photo_bytes=1_000_000, prefix="IMG_20100101_"):
        """干净照片行：名字自带日期（source=name），不成簇（各不同分钟）。"""
        rows = []
        for i in range(n):
            hh, mm = i // 60, i % 60
            rows.append(f"{prefix}{hh:02d}{mm:02d}00{i:03d}.jpg\t"
                        f"pad/\t{photo_bytes}\t2010-01-01\t2010-01-01\tname")
        return rows


# ---------------------------------------------------------------------------
# A1 账本解析
# ---------------------------------------------------------------------------

class ParseTest(LedgerTestCase):
    def test_a1_short_row(self):
        p = self.write("IMG_1.jpg\t2020-01-01\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("1 行", err)

    def test_a1_bytes_not_int(self):
        p = self.write("name\tpath\tabc\t2020-01-01\t-\tname\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("bytes 不是整数", err)

    def test_a1_bytes_negative(self):
        p = self.write("name\tpath\t-5\t2020-01-01\t-\tname\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("bytes 为负", err)

    def test_a1_birth_missing(self):
        p = self.write("name\tpath\t100\t\t-\tname\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("birth", err)

    def test_a1_birth_illegal(self):
        p = self.write("name\tpath\t100\t2023-13-40\t-\tname\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("birth 不是合法日期", err)

    def test_a1_birth_in_future(self):
        p = self.write("name\tpath\t100\t2027-01-01\t-\tname\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("未来", err)

    def test_a1_source_illegal(self):
        p = self.write("name\tpath\t100\t2020-01-01\t-\tguess\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("source", err)

    def test_a1_duplicate(self):
        row = "IMG_1.jpg\t2020/1\t100\t2020-01-01\t-\tname"
        p = self.write(row + "\n" + row + "\n")
        code, _, err = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 2)
        self.assertIn("重复登记", err)

    def test_a1_ledger_missing(self):
        code, _, err = run_cli("census",
                               os.path.join(self._tmp.name, "no.tsv"),
                               "--today", TODAY)
        self.assertEqual(code, 2)

    def test_a2_header_comment_blank_skipped(self):
        rows = ["name\tpath\tbytes\tbirth\tmtime\tsource",
                "# 这是一行注释",
                ""]
        rows += self.pad_rows()
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("30 件", out)

    def test_a1_source_optional_defaults_name(self):
        rows = self.pad_rows()
        rows[0] = "IMG_20100101_00000000.jpg\tpad/\t1000\t2010-01-01\t-"
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 0)   # 5 列缺 source 不炸，默认 name


# ---------------------------------------------------------------------------
# A3 出生日期考古
# ---------------------------------------------------------------------------

class DateArchaeologyTest(LedgerTestCase):
    CASES = [
        ("IMG_20230521_143022.jpg", date(2023, 5, 21)),
        ("IMG-20230521-WB0007.jpg", date(2023, 5, 21)),
        ("Screenshot 2026-01-05 at 09.12.33.png", date(2026, 1, 5)),
        ("Screenshot_20260105-091233.png", date(2026, 1, 5)),
        ("截屏2026-01-05 09.12.33.png", date(2026, 1, 5)),
        ("屏幕截图 2026-01-05 091233.png", date(2026, 1, 5)),
        ("WX20260105-091233.png", date(2026, 1, 5)),
        ("微信图片_20231102143022.jpg", date(2023, 11, 2)),
        ("WeChat Image 2023-11-02 143022.jpg", date(2023, 11, 2)),
        ("VID_20250214_193045.mp4", date(2025, 2, 14)),
        ("PXL_20240315_090000123456.TS.mp4", date(2024, 3, 15)),
        ("20230521_143022.jpg", date(2023, 5, 21)),
        ("2023-05-21 143022.jpg", date(2023, 5, 21)),
    ]

    def test_a3_name_date_patterns(self):
        for name, want in self.CASES:
            self.assertEqual(da.parse_name_date(name), want, name)

    def test_a3_no_date_returns_none(self):
        for name in ["DSC_0123.JPG", "IMG_1234.HEIC", "P1080321.JPG",
                     "mmexport1698900000000.jpg", "100APPLE_IMG_0034.JPG",
                     "photo.jpg"]:
            self.assertIsNone(da.parse_name_date(name), name)

    def test_a3_date_like_but_not_date(self):
        self.assertIsNone(da.parse_name_date("clip_20231332_000000.mp4"))
        self.assertIsNone(da.parse_name_date("IMG_20230230_000000.jpg"))  # 2/30

    def test_a3_time_component_never_wins(self):
        # 时间串 20 开头（20:2x 秒）不得抢在出生日期前面
        self.assertEqual(da.parse_name_date("IMG_20230521_202000.jpg"),
                         date(2023, 5, 21))


# ---------------------------------------------------------------------------
# A4/A5 身份判定与 burst 互查
# ---------------------------------------------------------------------------

class IdentityTest(LedgerTestCase):
    def test_a4_screenshot_family(self):
        for name in ["Screenshot 2026-01-05 at 09.12.33.png",
                     "Screenshot_20260105-091233.png",
                     "截屏2026-01-05 09.12.33.png",
                     "屏幕截图 2026-01-05 091233.png",
                     "WX20260105-091233.png"]:
            self.assertEqual(da.classify_base(name), "screenshot", name)

    def test_a4_chat_family(self):
        for name in ["微信图片_20231102143022.jpg",
                     "WeChat Image 2023-11-02 143022.jpg",
                     "WXIMG_20260105_091233.jpg"]:
            self.assertEqual(da.classify_base(name), "chat", name)

    def test_a4_video_by_ext(self):
        self.assertEqual(da.classify_base("VID_20250214_193045.mp4"), "video")
        self.assertEqual(da.classify_base("birthday.mov"), "video")

    def test_a4_screen_recording_is_screenshot(self):
        # 名字优先于扩展名：录屏是截图家族，不是照片视频
        self.assertEqual(da.classify_base("Screen Recording 2026-01-05.mp4"),
                         "screenshot")

    def test_a4_photo_fallback(self):
        self.assertEqual(da.classify_base("IMG_20230521_143022.jpg"), "photo")

    def mk(self, rows):
        lines = ["name\tpath\tbytes\tbirth\tmtime\tsource"]
        lines += rows
        return self.write("\n".join(lines) + "\n")

    def build(self, rows):
        items, _ = da.load_ledger(self.mk(rows), date(2026, 9, 1))
        return da.Library(items)

    @staticmethod
    def burst_row(hh, mm, ss, k, path="2023/"):
        return (f"IMG_20230521_{hh:02d}{mm:02d}{ss:02d}{k:03d}.jpg\t{path}\t"
                f"1000\t2023-05-21\t2023-05-21\tname")

    def test_a5_burst_cluster_of_3(self):
        rows = self.pad_rows()
        # 同一秒内连拍：时间戳不动、尾部序号递增（真实相机命名）
        rows += [self.burst_row(10, 30, 15, k) for k in (1, 2, 3)]
        lib = self.build(rows)
        self.assertEqual(lib.by_id_count["burst"], 3)

    def test_a5_two_shots_not_burst(self):
        rows = self.pad_rows()
        rows += [self.burst_row(10, 30, 15, k) for k in (1, 2)]
        lib = self.build(rows)
        self.assertEqual(lib.by_id_count["burst"], 0)

    def test_a5_same_day_scattered_not_burst(self):
        rows = self.pad_rows()
        # 同一天随手拍三张：时间戳跳变大（10:01 → 10:02 → 10:03 的
        # 完整时间串作序号，相邻差百万级），不是连拍
        rows += [self.burst_row(10, m, 30, 1) for m in (1, 2, 3)]
        lib = self.build(rows)
        self.assertEqual(lib.by_id_count["burst"], 0)

    def test_a5_cross_directory_not_burst(self):
        rows = self.pad_rows()
        rows += [self.burst_row(10, 30, 15, k, path=f"d{k}/")
                 for k in (1, 2, 3)]
        lib = self.build(rows)
        self.assertEqual(lib.by_id_count["burst"], 0)

    def test_a6_identity_identity_bytes(self):
        code, _, _ = run_cli("census", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)   # demo 红灯（见 A10）
        lib, _ = da.load_ledger(EXAMPLE, date(2026, 9, 1))
        library = da.Library(lib)
        self.assertEqual(sum(library.by_id_bytes.values()),
                         library.total_bytes)
        self.assertEqual(sum(library.by_id_count.values()), library.n)


# ---------------------------------------------------------------------------
# A7-A10 demo 钉数与门禁
# ---------------------------------------------------------------------------

class DemoNumbersTest(LedgerTestCase):
    @classmethod
    def setUpClass(cls):
        items, _ = da.load_ledger(EXAMPLE, date(2026, 9, 1))
        cls.lib = da.Library(items)

    def test_a7_demo_scale(self):
        self.assertEqual(self.lib.n, 1273)
        self.assertAlmostEqual(self.lib.total_bytes / da.GB, 302.9, places=1)

    def test_a7_dual_ruler_split(self):
        # 件数口径过半、字节口径几乎免费——本件的招牌分裂
        self.assertEqual(self.lib.junk_count, 644)
        self.assertAlmostEqual(self.lib.junk_count / self.lib.n, 0.506, places=3)
        self.assertGreater(self.lib.junk_count / self.lib.n, da.GATE_COUNT)
        self.assertAlmostEqual(self.lib.junk_bytes / self.lib.total_bytes,
                               0.003, places=3)
        self.assertEqual(self.lib.by_id_count["screenshot"], 330)
        self.assertEqual(self.lib.by_id_count["burst"], 224)
        self.assertEqual(self.lib.by_id_count["chat"], 90)
        self.assertEqual(self.lib.by_id_count["video"], 152)

    def test_a8_age_two_rulers(self):
        da.set_today(date(2026, 9, 1))
        by_count = da.library_median_age(self.lib) / 365.25
        by_bytes = da.library_median_age(self.lib, by_bytes=True) / 365.25
        self.assertAlmostEqual(by_count, 3.2, places=1)
        self.assertAlmostEqual(by_bytes, 1.9, places=1)
        self.assertGreater(by_count, by_bytes)   # 新的重，老的轻

    def test_a9_birth_sources(self):
        n_name = sum(1 for it in self.lib.items if it.source == "name")
        self.assertEqual(n_name, 1261)
        self.assertEqual(self.lib.n - n_name, 12)

    def test_a9_growth_line_sprint(self):
        da.set_today(date(2026, 9, 1))
        line = da.growth_line(self.lib, date(2026, 9, 1))
        self.assertIn("+19.7%", line)
        self.assertIn("加速", line)

    def test_a10_count_gate_red(self):
        code, out, _ = run_cli("census", EXAMPLE, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("判定 RED", out)
        self.assertIn("过半", out)

    def test_a10_bytes_gate_independent(self):
        # 10 件 2GB 录屏（screenshot）+ 30 件小照片：字节 99.9% RED、件数 25% 未过半
        rows = self.pad_rows()
        for i in range(10):
            rows.append(f"Screen Recording 2025-{i+1:02d}-01 10.00.00.mp4\t"
                        f"rec/\t{2 * 10**9}\t2025-{i+1:02d}-01\t-\tname")
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("junk", p, "--today", TODAY)
        self.assertEqual(code, 4)
        self.assertIn("字节超三成", out)

    def test_a10_green_library(self):
        rows = self.pad_rows(40)
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("census", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("判定 GREEN", out)

    def test_a11_thin_below_30(self):
        rows = self.pad_rows(12)
        p = self.write("\n".join(rows) + "\n")
        for cmd, extra in [("census", []), ("pyramid", []), ("junk", []),
                           ("rent", ["--price", "21", "--quota", "200"]),
                           ("simulate", ["--prune", "junk"])]:
            code, _, err = run_cli(cmd, p, "--today", TODAY, *extra)
            self.assertEqual(code, 3, cmd)
            self.assertIn("不足 30", err)


# ---------------------------------------------------------------------------
# A12 房租
# ---------------------------------------------------------------------------

class RentTest(LedgerTestCase):
    def test_a12_unit_price(self):
        self.assertAlmostEqual(da.unit_price(68, 2048), 0.033203125)
        self.assertAlmostEqual(da.unit_price(21, 200), 0.105)

    def test_a12_census_rent_line(self):
        code, out, _ = run_cli("census", EXAMPLE, "--today", TODAY,
                               "--price", "68", "--quota", "2048")
        self.assertEqual(code, 4)
        self.assertIn("¥10.06/月", out)
        self.assertIn("¥120.7/年", out)
        self.assertIn("视频房租 ¥9.97/月（99.1%）", out)

    def test_a12_no_price_no_rent(self):
        code, out, _ = run_cli("census", EXAMPLE, "--today", TODAY)
        self.assertIn("不发明单价", out)
        self.assertNotIn("¥", out.split("房租")[1].split("\n")[0])

    def test_a12_rent_command_sorted(self):
        code, out, _ = run_cli("rent", EXAMPLE, "--price", "68",
                               "--quota", "2048")
        self.assertEqual(code, 0)
        self.assertIn("视频", out.split("\n")[2])   # 按月租降序，视频第一
        self.assertIn("总租 ¥10.06/月", out)

    def test_a12_rent_over_quota_banner(self):
        code, out, _ = run_cli("rent", EXAMPLE, "--price", "21",
                               "--quota", "200")
        self.assertIn("超你给的 200 GB 档", out)

    def test_a12_rent_requires_args(self):
        code, _, _ = run_cli("rent", EXAMPLE)
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# A13 金字塔
# ---------------------------------------------------------------------------

class PyramidTest(LedgerTestCase):
    def test_a13_year_rows(self):
        code, out, _ = run_cli("pyramid", EXAMPLE)
        self.assertEqual(code, 0)
        years = re.findall(r"^  (20\d{2})  █", out, re.M)
        self.assertEqual(years, ["2019", "2020", "2021", "2022", "2023",
                                 "2024", "2025", "2026"])

    def test_a13_bar_width_normalized(self):
        code, out, _ = run_cli("pyramid", EXAMPLE)
        bars = re.findall(r"^  (20\d{2})  (█+)", out, re.M)
        counts = {y: int(n) for y, n in
                  re.findall(r"^  (20\d{2})  █+\s+(\d+) 件", out, re.M)}
        maxc = max(counts.values())
        for y, bar in bars:
            want = max(1, round(counts[y] / maxc * 36))
            self.assertEqual(len(bar), want, y)

    def test_a13_bytes_younger_note(self):
        code, out, _ = run_cli("pyramid", EXAMPLE)
        self.assertIn("库在变重，不在变老", out)


# ---------------------------------------------------------------------------
# A14 simulate
# ---------------------------------------------------------------------------

class SimulateTest(LedgerTestCase):
    def test_a14_junk_equals_three_parts(self):
        lib, _ = da.load_ledger(EXAMPLE, date(2026, 9, 1))
        library = da.Library(lib)
        victims, _ = da.prune_subset(library, "junk", 5)
        self.assertEqual(len(victims), library.junk_count)
        self.assertEqual(sum(it.bytes for it in victims), library.junk_bytes)
        shots, _ = da.prune_subset(library, "screenshots", 5)
        bursts, _ = da.prune_subset(library, "bursts", 5)
        chats, _ = da.prune_subset(library, "chats", 5)
        self.assertEqual(len(shots) + len(bursts) + len(chats), len(victims))

    def test_a14_prune_junk_green_survivor(self):
        code, out, _ = run_cli("simulate", EXAMPLE, "--prune", "junk",
                               "--today", TODAY, "--price", "68",
                               "--quota", "2048")
        self.assertEqual(code, 0)
        self.assertIn("644 件 933 MB 出库", out)
        self.assertIn("幸存库体检", out)
        self.assertIn("GREEN", out)
        self.assertIn("省 0.3% 字节", out)
        self.assertIn("永不执行删除", out)

    def test_a14_prune_videos_landlord_leaves(self):
        # 大房东一走，垃圾露出原形：字节口径 0.3% → 34.3% 翻红
        code, out, _ = run_cli("simulate", EXAMPLE, "--prune", "videos",
                               "--today", TODAY, "--price", "68",
                               "--quota", "2048")
        self.assertEqual(code, 0)
        self.assertIn("152 件 300.2 GB 出库", out)
        self.assertIn("¥10.06/月 → ¥0.09/月", out)
        self.assertIn("34.3%", out)
        self.assertIn("RED", out)

    def test_a14_simulate_never_exit_4(self):
        # 对着全红灯的库推演，simulate 也不亮门禁——它只算术
        for prune in ("junk", "videos", "screenshots", "bursts", "chats",
                      "aged"):
            code, _, _ = run_cli("simulate", EXAMPLE, "--prune", prune,
                                 "--today", TODAY)
            self.assertNotEqual(code, 4, prune)

    def test_a14_aged_zero_years_refused(self):
        code, _, err = run_cli("simulate", EXAMPLE, "--prune", "aged",
                               "--years", "0", "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("--years", err)

    def test_a14_empty_subset_exit_3(self):
        rows = self.pad_rows(40)   # 无任何垃圾
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("simulate", p, "--prune", "chats",
                               "--today", TODAY)
        self.assertEqual(code, 3)
        self.assertIn("没有可推演的对象", out)

    def test_a14_aged_banner(self):
        code, out, _ = run_cli("simulate", EXAMPLE, "--prune", "aged",
                               "--years", "5", "--today", TODAY)
        self.assertIn("aged ≠ 该删", out)

    def test_a14_aged_median_age_drops(self):
        code, out, _ = run_cli("simulate", EXAMPLE, "--prune", "aged",
                               "--years", "5", "--today", TODAY)
        self.assertIn("3.2 年 → 2.5 年", out)


# ---------------------------------------------------------------------------
# A15 scan
# ---------------------------------------------------------------------------

class ScanTest(LedgerTestCase):
    def touch(self, rel, size, iso):
        """造一个真实文件并把 mtime 钉死（CI 上稳定）。"""
        import datetime as dt
        import time as _time
        full = os.path.join(self._tmp.name, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"\0" * size)
        ts = _time.mktime(dt.datetime.fromisoformat(iso).timetuple())
        os.utime(full, (ts, ts))

    def test_a15_scan_name_and_mtime_sources(self):
        self.touch("2024/IMG_20240501_120000.jpg", 100, "2020-01-01 00:00:00")
        self.touch("2024/DSC_00001.JPG", 100, "2019-08-14 08:00:00")
        out_path = os.path.join(self._tmp.name, "out.tsv")
        code, _, _ = run_cli("scan", self._tmp.name, "-o", out_path)
        self.assertEqual(code, 0)
        rows = {}
        with open(out_path, encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                cols = line.rstrip("\n").split("\t")
                rows[cols[0]] = cols
        # 名字自带日期：source=name，birth 从文件名，无视 mtime（2020）
        r = rows["IMG_20240501_120000.jpg"]
        self.assertEqual((r[3], r[5]), ("2024-05-01", "name"))
        # 无日期名：source=mtime，birth = mtime
        r = rows["DSC_00001.JPG"]
        self.assertEqual((r[3], r[5]), ("2019-08-14", "mtime"))

    def test_a15_squatters_not_enrolled(self):
        self.touch("IMG_20240501_120000.jpg", 100, "2024-05-01 00:00:00")
        self.touch("notes.pdf", 10, "2024-05-01 00:00:00")
        self.touch(".DS_Store", 4, "2024-05-01 00:00:00")
        out_path = os.path.join(self._tmp.name, "out.tsv")
        code, out, _ = run_cli("scan", self._tmp.name, "-o", out_path)
        self.assertEqual(code, 0)
        with open(out_path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertEqual(body.count("\n"), 2)   # 表头 + 1 件媒体
        self.assertIn("寄居户 2", out)

    def test_a15_scan_to_census_loop(self):
        for i in range(32):
            hh, mm = i // 60, i % 60
            self.touch(f"IMG_20240501_{hh:02d}{mm:02d}00{i:03d}.jpg", 100,
                       "2024-05-01 00:00:00")
        out_path = os.path.join(self._tmp.name, "out.tsv")
        code, _, _ = run_cli("scan", self._tmp.name, "-o", out_path)
        self.assertEqual(code, 0)
        code, out, _ = run_cli("census", out_path, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("32 件", out)
        self.assertIn("文件名考古 32 件（100.0%）", out)

    def test_a15_empty_and_missing_dirs(self):
        code, _, err = run_cli("scan", os.path.join(self._tmp.name, "void"))
        self.assertEqual(code, 3)
        empty = os.path.join(self._tmp.name, "empty")
        os.makedirs(empty)
        code, _, err = run_cli("scan", empty)
        self.assertEqual(code, 3)
        self.assertIn("空房间", err)


# ---------------------------------------------------------------------------
# A16-A19 纪律
# ---------------------------------------------------------------------------

class DisciplineTest(LedgerTestCase):
    def test_a16_today_pins_bytes(self):
        outs = []
        for _ in range(2):
            code, out, _ = run_cli("census", EXAMPLE, "--today", TODAY,
                                   "--price", "68", "--quota", "2048")
            outs.append(out)
        self.assertEqual(outs[0], outs[1])

    def test_a16_age_moves_with_today(self):
        da.set_today(date(2026, 9, 1))
        age_2026 = da.library_median_age(da.Library(
            da.load_ledger(EXAMPLE, date(2026, 9, 1))[0]))
        da.set_today(date(2027, 9, 1))
        age_2027 = da.library_median_age(da.Library(
            da.load_ledger(EXAMPLE, date(2027, 9, 1))[0]))
        da.set_today(date.today())   # 还原
        self.assertAlmostEqual(age_2027 - age_2026, 365.25, delta=2)

    def test_a17_validate_mtime_warning(self):
        rows = []
        for i in range(30):
            rows.append(f"DSC_{i:05d}.JPG\tflat/\t1000\t2015-03-01\t"
                        f"2015-03-01\tmtime")
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("validate", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("超三成", out)
        self.assertIn("估的", out)

    def test_a17_validate_same_name_across_dirs(self):
        rows = self.pad_rows()
        rows.append("IMG_1.jpg\ta/\t100\t2020-01-01\t-\tname")
        rows.append("IMG_1.jpg\tb/\t100\t2020-01-01\t-\tname")
        p = self.write("\n".join(rows) + "\n")
        code, out, _ = run_cli("validate", p, "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("同名文件", out)

    def test_a18_no_absolute_path_in_reports(self):
        for cmd, extra in [("census", []), ("pyramid", []), ("junk", []),
                           ("validate", []),
                           ("rent", ["--price", "68", "--quota", "2048"]),
                           ("simulate", ["--prune", "junk"])]:
            code, out, _ = run_cli(cmd, EXAMPLE, "--today", TODAY, *extra)
            self.assertNotIn(BASE, out, cmd)
            self.assertNotIn("/Users/", out, cmd)

    def test_a19_stdlib_only(self):
        src = os.path.join(BASE, "digital_attic.py")
        with open(src, encoding="utf-8") as fh:
            tree = fh.read()
        imports = set(re.findall(r"^import (\w+)", tree, re.M))
        imports |= set(re.findall(r"^from (\w+)", tree, re.M))
        self.assertTrue(imports <= {"argparse", "datetime", "os", "re",
                                    "sys", "collections", "typing",
                                    "__future__"},
                        imports)


if __name__ == "__main__":
    unittest.main()
