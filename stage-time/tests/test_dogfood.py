"""Dogfood：对本仓库自带的示例演讲稿跑全流程，快照锁定输出。

examples/demo_talk.md 是一篇真实的 15 分钟级技术分享稿（主题致敬本仓库
的 gitweek：周报在说谎）。它被刻意设计成「三病齐发」：
  1. 超时（15.8 分钟 @ 15 分钟预算）；
  2. 核心主张句出现在 64% 处（太晚）；
  3. 含客套开场与冗长背景（压缩清单有靶子）。
本测试验证三病都能被工具检出，且输出与快照逐字节一致（确定性）。
"""

import contextlib
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
EXAMPLES = os.path.join(PKG, "examples")

sys.path.insert(0, PKG)
import stage_time as st  # noqa: E402


def run_cli(argv):
    """在 stage-time/ 目录下运行（快照中的讲稿路径为相对路径）。"""
    cwd = os.getcwd()
    os.chdir(PKG)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = st.main(argv)
        return rc, buf.getvalue()
    finally:
        os.chdir(cwd)


def snapshot(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
        return f.read()


class TestDogfood(unittest.TestCase):
    def test_demo_talk_exists_with_all_blocks(self):
        with open(os.path.join(EXAMPLES, "demo_talk.md"), encoding="utf-8") as f:
            blocks = st.parse_blocks(f.read())
        kinds = {b[0] for b in blocks}
        self.assertIn("heading", kinds)
        self.assertIn("list_item", kinds)
        self.assertIn("code", kinds)
        self.assertGreater(len(blocks), 30)

    def test_estimate_detects_overrun_and_matches_snapshot(self):
        rc, out = run_cli(["estimate", "examples/demo_talk.md",
                           "--budget", "15"])
        self.assertEqual(rc, 0)
        self.assertIn("⚠️", out)          # 超时被写稿时的估算抓住
        self.assertIn("15.0 分钟", out)
        self.assertEqual(out, snapshot("sample-estimate.txt"))

    def test_thesis_flags_late_position_and_matches_snapshot(self):
        rc, out = run_cli(["thesis", "examples/demo_talk.md"])
        self.assertEqual(rc, 0)
        self.assertIn("🔴", out)          # 主张句太晚
        self.assertEqual(out, snapshot("sample-thesis.txt"))

    def test_cuts_cover_overrun_and_match_snapshot(self):
        rc, out = run_cli(["cuts", "examples/demo_talk.md",
                           "--budget", "15"])
        self.assertEqual(rc, 0)
        self.assertIn("已覆盖需求", out)
        self.assertIn("核心内容", out)     # 保护声明在场
        self.assertEqual(out, snapshot("sample-cuts.txt"))

    def test_cuts_never_touch_thesis_block(self):
        rc, out = run_cli(["cuts", "examples/demo_talk.md",
                           "--budget", "15", "--json"])
        payload = __import__("json").loads(out)
        for sug in payload["suggestions"]:
            self.assertNotIn("真正的问题", sug["text"])


if __name__ == "__main__":
    unittest.main()
