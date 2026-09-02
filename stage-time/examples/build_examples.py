#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成 examples/ 下的 dogfood 快照（确定性：无时间戳，路径相对固定）。

用法：python3 examples/build_examples.py
"""

import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)  # stage-time/
sys.path.insert(0, PKG)

import stage_time  # noqa: E402

SNAPSHOTS = [
    ("sample-estimate.txt",
     ["estimate", "examples/demo_talk.md", "--budget", "15"]),
    ("sample-thesis.txt",
     ["thesis", "examples/demo_talk.md"]),
    ("sample-cuts.txt",
     ["cuts", "examples/demo_talk.md", "--budget", "15"]),
]


def main():
    os.chdir(PKG)  # 快照中的讲稿路径保持相对，跨机器可比
    for name, argv in SNAPSHOTS:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = stage_time.main(argv)
        if rc != 0:
            raise SystemExit("生成 %s 失败：exit %d" % (name, rc))
        with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print("已写入 %s（%d 字节）" % (name, len(buf.getvalue())))


if __name__ == "__main__":
    main()
