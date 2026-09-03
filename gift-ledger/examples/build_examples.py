#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建 examples/ 下全部样例输出（钉死 --as-of，逐字节可复现）。

用法：
  python3 examples/build_examples.py           # 重建并覆盖
  python3 examples/build_examples.py --check   # 只比对，逐字节一致才 exit 0
"""

import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "gift_ledger.py")
LEDGER = os.path.join(HERE, "gifts.tsv")
AS_OF = "2026-09-04"

CASES = [
    ("sample-ledger.txt",
     ["ledger", LEDGER, "--as-of", AS_OF], 0),
    ("sample-balance-brother.txt",
     ["balance", LEDGER, "表哥", "--as-of", AS_OF], 0),
    ("sample-balance-aunt.txt",
     ["balance", LEDGER, "姑姑", "--as-of", AS_OF], 0),
    ("sample-suggest-cousin.txt",
     ["suggest", LEDGER, "表妹", "--occasion", "wedding",
      "--as-of", AS_OF], 0),
    ("sample-suggest-aunt.txt",
     ["suggest", LEDGER, "姑姑", "--occasion", "baby", "--as-of", AS_OF], 0),
    ("sample-book.txt",
     ["book", LEDGER, "--as-of", AS_OF], 4),
    ("sample-inflation.txt",
     ["inflation", LEDGER, "--as-of", AS_OF], 0),
    ("sample-simulate.txt",
     ["simulate", LEDGER, "老周", "--amount", "300", "--as-of", AS_OF], 0),
]


def build(tmpdir: str) -> list:
    written = []
    for name, argv, expected in CASES:
        proc = subprocess.run([sys.executable, CLI] + argv,
                              capture_output=True, text=True)
        if proc.returncode != expected:
            print("!! %s 退出码 %d（期望 %d）\n%s" % (
                name, proc.returncode, expected, proc.stderr), file=sys.stderr)
            sys.exit(1)
        out = proc.stdout
        # 把绝对路径换成相对路径，样例在谁的机器上都长得一样
        out = out.replace(LEDGER, "examples/gifts.tsv").replace(CLI, "gift_ledger.py")
        path = os.path.join(tmpdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
        written.append((name, path))
    return written


def main() -> int:
    if "--check" in sys.argv[1:]:
        tmpdir = tempfile.mkdtemp(prefix="gift-ledger-examples-")
        ok = True
        for name, path in build(tmpdir):
            target = os.path.join(HERE, name)
            if not os.path.exists(target):
                print("!! %s 不存在" % name, file=sys.stderr)
                ok = False
            elif not filecmp.cmp(path, target, shallow=False):
                print("!! %s 与重建结果不一致" % name, file=sys.stderr)
                ok = False
            else:
                print("ok %s" % name)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 0 if ok else 1
    for name, path in build(tempfile.mkdtemp(prefix="gift-ledger-examples-")):
        target = os.path.join(HERE, name)
        shutil.copyfile(path, target)
        print("ok %s" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
