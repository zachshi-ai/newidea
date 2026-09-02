"""Acceptance tests for stage_time.py — all criteria from README.

设计原则：所有时长断言用 --rate 注入固定语速（单位/秒），消除默认值
浮动；结构停顿用「同字数对照」断言，不依赖绝对秒数。
"""

import io
import json
import contextlib
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = [sys.executable, os.path.join(ROOT, "stage_time.py")]

sys.path.insert(0, ROOT)
import stage_time as st  # noqa: E402


def run_main(argv):
    """在进程内跑 CLI，返回 (exit_code, stdout)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = st.main(argv)
    return rc, buf.getvalue()


def write_talk(text, directory=None):
    fd, path = tempfile.mkstemp(suffix=".md", dir=directory, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


CJK = "字" * 100  # 100 口播单位


# ---------------------------------------------------------------- 文本度量
class TestUnits(unittest.TestCase):
    def test_cjk_one_unit_per_char(self):
        self.assertEqual(st.text_units("你好世界"), 4)

    def test_digit_run_read_digit_by_digit(self):
        # 「2024」逐位念（二-零-二-四）＝4 单位，与「二零二四」等价
        self.assertEqual(st.text_units("版本2024"), st.text_units("版本二零二四"))

    def test_english_word_units(self):
        self.assertAlmostEqual(st.text_units("hello world"), 3.6)

    def test_inline_code_not_in_units(self):
        # 行内代码按字符秒数单独计，不占叙述单位
        self.assertEqual(st.text_units("运行`git log`命令"),
                         st.text_units("运行命令"))

    def test_mixed_text(self):
        # 4 汉字（发布于年）+「2024」逐位 4 + 2 英文词 3.6
        self.assertAlmostEqual(st.text_units("发布于2024年，ship it"),
                               4 + 4 + 3.6)


# ---------------------------------------------------------------- 时长模型
class TestDurationModel(unittest.TestCase):
    def test_baseline_narrative(self):
        # 480 单位 @4/s = 120 秒，单块无停顿
        blocks = st.parse_blocks("字" * 480)
        total, _ = st.timeline(blocks, ups=4.0)
        self.assertAlmostEqual(total, 120.0, places=6)

    def test_code_block_slower_than_prose(self):
        # 同样的字符，念代码（逐字符+演示停顿）比当英文散文读更慢
        cmd = "git log --since last week --author me --no-merges --stat"
        prose = st.parse_blocks(cmd)
        code = st.parse_blocks("```\n%s\n```" % cmd)
        t_prose, _ = st.timeline(prose, ups=4.0)
        t_code, _ = st.timeline(code, ups=4.0)
        self.assertGreater(t_code, t_prose)

    def test_list_pauses_counted(self):
        # 5×20 字列表 vs 同字数整段：列表多出 4 次项间停顿
        listed = "\n".join("- " + "字" * 20 for _ in range(5))
        t_list, _ = st.timeline(st.parse_blocks(listed), ups=4.0)
        t_para, _ = st.timeline(st.parse_blocks("字" * 100), ups=4.0)
        self.assertAlmostEqual(t_list - t_para, 4 * st.LIST_ITEM_PAUSE, places=6)

    def test_heading_pause_counted(self):
        bare = st.parse_blocks("字" * 50)
        with_h = st.parse_blocks("# 标题\n\n" + "字" * 50)
        t_bare, _ = st.timeline(bare, ups=4.0)
        t_with, per = st.timeline(with_h, ups=4.0)
        # 差值 = 标题自身念读 + 翻页停顿 + 与后段的段落停顿
        self.assertAlmostEqual(t_with - t_bare,
                               st.text_units("标题") / 4
                               + st.HEADING_PAUSE + st.PARAGRAPH_PAUSE,
                               places=6)

    def test_per_block_kinds(self):
        blocks = st.parse_blocks(
            "# 标题\n\n段落一。\n\n- 项 A\n- 项 B\n\n> 引用\n\n```\ncode\n```\n")
        kinds = [b[0] for b in blocks]
        self.assertEqual(kinds, ["heading", "paragraph", "list_item",
                                 "list_item", "quote", "code"])


# ---------------------------------------------------------------- 预算判定
class TestBudget(unittest.TestCase):
    def test_over_budget(self):
        path = write_talk("字" * 480)  # 120 秒
        self.addCleanup(os.remove, path)
        data = st.estimate_data(path, ups=4.0, budget_seconds=60.0)
        self.assertEqual(data["verdict"], "over")
        self.assertAlmostEqual(data["overrun_seconds"], 60.0, places=6)

    def test_within_budget(self):
        path = write_talk("字" * 480)
        self.addCleanup(os.remove, path)
        data = st.estimate_data(path, ups=4.0, budget_seconds=180.0)
        self.assertEqual(data["verdict"], "within")
        self.assertAlmostEqual(data["overrun_seconds"], -60.0, places=6)

    def test_cli_overrun_message(self):
        path = write_talk("字" * 480)
        self.addCleanup(os.remove, path)
        rc, out = run_main(["estimate", path, "--budget", "1", "--rate", "4"])
        self.assertEqual(rc, 0)
        self.assertIn("超时", out)
        self.assertIn("cuts", out)


# ---------------------------------------------------------------- 压缩清单
class TestCuts(unittest.TestCase):
    TALK = """# 分享标题

首先，感谢大家在百忙之中拨冗出席，废话不多说，接下来我将开始。

很久以前，在过去的行业里，这类制度的传统做法是手工登记造册，沿用多年。

我认为核心主张在这里，论证的关键内容绝对不能删，一句都不行。

举个例子，具体来说这里有一段次要的细节展开，可以牺牲。
"""

    def _result(self, budget_seconds, talk=None):
        talk = talk or self.TALK
        blocks = st.parse_blocks(talk)
        return st.build_cuts(blocks, ups=4.0, budget_seconds=budget_seconds)

    def test_priority_order_and_protection(self):
        r = self._result(budget_seconds=30.0)  # 32 秒的稿子：轻微超时
        priorities = [s["priority"] for s in r["suggestions"]]
        self.assertEqual(priorities, sorted(priorities))
        for sug in r["suggestions"]:
            self.assertNotIn("核心主张", sug["text"])
        self.assertGreater(r["protected_blocks"], 0)

    def test_cuts_cover_overrun_with_margin(self):
        r = self._result(budget_seconds=30.0)
        self.assertTrue(r["covered"])
        self.assertGreaterEqual(r["suggestions"][-1]["cumulative"],
                                r["need_seconds"])

    def test_need_includes_safety_margin(self):
        r = self._result(budget_seconds=30.0)
        self.assertAlmostEqual(r["need_seconds"],
                               r["overrun_seconds"] * st.SAFETY_MARGIN,
                               places=6)

    def test_uncoverable_when_pool_too_small(self):
        # 只有保护块 + 一个小客套：删光也不够 → covered=False
        talk = "我认为核心论证很长。" * 30 + "\n\n谢谢大家。"
        r = self._result(budget_seconds=1.0, talk=talk)
        self.assertFalse(r["covered"])

    def test_min_cut_filter(self):
        # 省 5 秒以下的块不进清单（省 2 秒的建议是噪音）
        talk = "我认为核心论证。" * 40 + "\n\n感谢大家百忙之中。\n\n谢谢大家。"
        r = self._result(budget_seconds=1.0, talk=talk)
        for sug in r["suggestions"]:
            self.assertGreaterEqual(sug["seconds"], st.MIN_CUT_SECONDS)

    def test_no_overrun_no_cuts(self):
        r = self._result(budget_seconds=60 * 60)
        self.assertLessEqual(r["overrun_seconds"], 0)
        rc, out = run_main(["cuts", write_talk("我认为短稿足够。"),
                            "--budget", "60", "--rate", "4"])
        self.assertIn("未超时", out)


# ---------------------------------------------------------------- 主张位置
class TestThesis(unittest.TestCase):
    def test_thesis_found_with_position(self):
        talk = "铺垫一。铺垫二。\n\n我认为核心主张是每周对账。后续论证。"
        found = st.find_thesis(st.parse_blocks(talk), ups=4.0)
        self.assertIsNotNone(found)
        sentence, pct, _ = found
        self.assertIn("对账", sentence)
        self.assertGreater(pct, 0.0)
        self.assertLess(pct, 1.0)

    def test_thesis_early_vs_late(self):
        early = "我认为主张要前置。" + "铺垫。" * 200
        late = "铺垫。" * 200 + "我认为主张放得太晚了。"
        _, pct_early = st.find_thesis(st.parse_blocks(early), ups=4.0)[:-1]
        _, pct_late = st.find_thesis(st.parse_blocks(late), ups=4.0)[:-1]
        self.assertLessEqual(pct_early, 0.25)
        self.assertGreater(pct_late, 0.50)

    def test_thesis_absent_returns_none(self):
        talk = "只是铺垫，没有任何主张信号词。" * 10
        self.assertIsNone(st.find_thesis(st.parse_blocks(talk), ups=4.0))

    def test_cli_verdicts(self):
        late_talk = "铺垫。" * 200 + "我认为太晚了。"
        path = write_talk(late_talk)
        self.addCleanup(os.remove, path)
        _, out = run_main(["thesis", path, "--rate", "4"])
        self.assertIn("🔴", out)
        none_path = write_talk("没有任何信号词。" * 10)
        self.addCleanup(os.remove, none_path)
        _, out = run_main(["thesis", none_path, "--rate", "4"])
        self.assertIn("未检出", out)


# ---------------------------------------------------------------- 校准
class TestCalibrate(unittest.TestCase):
    def test_roundtrip_recovers_rate(self):
        talk = "# 标题\n\n" + "正文叙述。" * 80 + "\n\n- 项一\n- 项二\n\n```\nls -la\n```\n"
        blocks = st.parse_blocks(talk)
        true_ups = 3.2
        actual_total, _ = st.timeline(blocks, ups=true_ups)
        ups_star = st.calibrate_ups(blocks, actual_total)
        self.assertAlmostEqual(ups_star, true_ups, places=6)
        # 用校准速率重估，总时长还原为真实时长（含固定成本）
        replay_total, _ = st.timeline(blocks, ups=ups_star)
        self.assertAlmostEqual(replay_total, actual_total, places=4)

    def test_rejects_impossible_actual(self):
        blocks = st.parse_blocks("```\n" + "x" * 200 + "\n```")  # 固定成本 26s
        with self.assertRaises(ValueError):
            st.calibrate_ups(blocks, actual_seconds=10.0)

    def test_cli_save_and_reuse_profile(self):
        talk = "# 标\n\n" + "正文字。" * 100
        path = write_talk(talk)
        self.addCleanup(os.remove, path)
        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "profile.json")
            rc, out = run_main(["calibrate", path, "--actual", "10",
                                "--rate", "4", "--save",
                                "--profile", profile])
            self.assertEqual(rc, 0)
            with open(profile, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("units_per_second", data)
            # estimate 挂上档案后应回放到 10 分钟
            rc, out = run_main(["estimate", path, "--budget", "15",
                                "--json", "--profile", profile])
            payload = json.loads(out)
            self.assertAlmostEqual(payload["minutes"], 10.0, places=1)


# ---------------------------------------------------------------- CLI 行为
class TestCli(unittest.TestCase):
    def test_missing_file_fails_cleanly(self):
        rc, _ = run_main(["estimate", "/nonexistent/talk.md", "--budget", "10"])
        self.assertEqual(rc, 2)

    def test_json_estimate_shape(self):
        path = write_talk("我认为主张很短。")
        self.addCleanup(os.remove, path)
        rc, out = run_main(["estimate", path, "--budget", "1", "--json",
                            "--rate", "4"])
        payload = json.loads(out)
        for key in ("units", "minutes", "band", "verdict", "overrun_seconds"):
            self.assertIn(key, payload)

    def test_deterministic_output(self):
        path = write_talk("# t\n\n" + "正文。" * 60 + "\n\n- 一\n- 二\n")
        self.addCleanup(os.remove, path)
        argv = ["estimate", path, "--budget", "2", "--rate", "4"]
        rc1, out1 = run_main(argv)
        rc2, out2 = run_main(argv)
        self.assertEqual((rc1, out1), (rc2, out2))

    def test_english_talk_supported(self):
        path = write_talk(
            "# Hello\n\nI argue that we must fix weekly reports now. "
            "Filler sentence to add some length here.\n\n- item one\n- item two\n")
        self.addCleanup(os.remove, path)
        rc, out = run_main(["estimate", path, "--budget", "0.05",
                            "--rate", "4"])
        self.assertEqual(rc, 0)
        self.assertIn("超时", out)
        rc, out = run_main(["thesis", path, "--rate", "4"])
        self.assertIn("I argue", out)

    def test_subprocess_entry(self):
        path = write_talk("我认为很快。")
        self.addCleanup(os.remove, path)
        proc = subprocess.run(CLI + ["estimate", path, "--budget", "1",
                                     "--rate", "4"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("讲台时刻", proc.stdout)


if __name__ == "__main__":
    unittest.main()
