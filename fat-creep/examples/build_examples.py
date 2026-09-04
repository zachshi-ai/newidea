#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缓胖 · Fat Creep —— 生成样例账本并用真 CLI 渲染快照。

python3 build_examples.py          # 生成账本 + 全部快照
python3 build_examples.py --check  # 逐字节校验（CI 用）

快照里有两类：
  - 绿灯快照（cost / diet / validate / report 重放 2026-03-20）：exit 0；
  - 红灯快照（report / trend / due / diet --deadline）：exit 4 是演示主体，
    本脚本容忍红灯退出码，但断言 validate 与重放必须干净。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable or "python3"
CLI = os.path.join(ROOT, "fat_creep.py")
W = os.path.join(HERE, "weights.tsv")
E = os.path.join(HERE, "events.tsv")
SNAP = os.path.join(HERE, "snapshots")

WEIGHTS_TSV = """# 缓胖 · Fat Creep 样例秤账 —— 三只宠：胖橘（蠕涨）、豆包（平稳）、糯米（新领养薄账）
# date\tpet\tweight_kg\tnote
date\tpet\tweight_kg\tnote
2025-07-01\t胖橘\t4.10\t绝育后基线
2025-08-02\t胖橘\t4.15
2025-09-03\t胖橘\t4.19
2025-10-06\t胖橘\t4.24
2025-11-08\t胖橘\t4.28
2025-12-11\t胖橘\t4.33
2026-01-13\t胖橘\t4.37
2026-02-15\t胖橘\t4.41
2026-03-20\t胖橘\t4.48
2026-04-22\t胖橘\t4.55
2026-05-25\t胖橘\t4.62
2026-06-27\t胖橘\t4.68
2026-07-30\t胖橘\t4.75\t夏天食欲旺盛
2026-09-01\t胖橘\t4.86
2026-03-05\t豆包\t8.20\t领养体检记录
2026-04-06\t豆包\t8.14
2026-05-08\t豆包\t8.22
2026-06-09\t豆包\t8.18
2026-07-12\t豆包\t8.25
2026-08-13\t豆包\t8.19
2026-09-01\t豆包\t8.23
2026-08-20\t糯米\t2.35\t接回家
2026-09-03\t糯米\t2.41\t幼猫生长中
"""

EVENTS_TSV = """# 缓胖 · Fat Creep 样例事件账 —— kind ∈ care | cost；care 行金额计入开销账（一行两用，不双记）
# date\tpet\tkind\titem\tamount\tnote
date\tpet\tkind\titem\tamount\tnote
2025-09-15\t胖橘\tcare\t狂犬疫苗\t80\t社区卫生站
2025-09-15\t胖橘\tcare\t猫三联\t180
2025-09-20\t胖橘\tcare\t体检\t300\t基础体检套餐
2025-10-12\t胖橘\tcost\t渴望鸡猫粮 6kg\t385\t涨价前 385
2026-01-08\t胖橘\tcost\t尿闭住院 4 天\t2600\t公猫高发 导尿+住院
2026-01-08\t胖橘\tcost\t处方罐头 x6\t180\t术后处方粮
2026-02-20\t胖橘\tcost\t渴望鸡猫粮 6kg\t385
2026-03-15\t胖橘\tcost\t猫砂 4 袋\t120
2026-05-30\t胖橘\tcost\t渴望鸡猫粮 6kg\t385
2026-06-10\t胖橘\tcare\t体内驱虫\t40
2026-06-18\t胖橘\tcost\t猫抓板\t45
2026-07-25\t胖橘\tcare\t体外驱虫\t60\t八月那次忘了
2026-08-10\t胖橘\tcost\t渴望鸡猫粮 6kg\t399\t涨价了
2025-12-10\t豆包\tcare\t体检\t280\t领养前基线
2026-01-20\t豆包\tcare\t狂犬疫苗\t60
2026-01-20\t豆包\tcare\t犬四联\t160
2026-01-22\t豆包\tcost\t大型犬粮 12kg\t320
2026-03-20\t豆包\tcost\t大型犬粮 12kg\t320
2026-05-25\t豆包\tcost\t洗澡美容\t120
2026-06-01\t豆包\tcost\t牵引绳\t65
2026-07-28\t豆包\tcost\t大型犬粮 12kg\t335\t换包装涨了
2026-08-28\t豆包\tcare\t体内驱虫\t35
"""

# (name, argv_without_files, allowed_exit_codes)
SNAPSHOTS = [
    ("report", ["report", "--as-of", "2026-09-03"], {0, 4}),
    ("report-replay", ["report", "--as-of", "2026-03-20"], {0}),
    ("trend", ["trend"], {0, 4}),
    ("due", ["due"], {0, 4}),
    ("cost", ["cost"], {0}),
    ("diet", ["diet", "--pet", "胖橘", "--target", "4.40"], {0}),
    ("diet-deadline", ["diet", "--pet", "胖橘", "--target", "4.40", "--deadline", "2026-09-25"], {0, 4}),
    ("validate", ["validate"], {0}),
]


def run(argv):
    return subprocess.run([PY, CLI] + argv, capture_output=True, text=True, encoding="utf-8")


def build():
    with open(W, "w", encoding="utf-8") as f:
        f.write(WEIGHTS_TSV)
    with open(E, "w", encoding="utf-8") as f:
        f.write(EVENTS_TSV)
    os.makedirs(SNAP, exist_ok=True)
    for name, argv, allowed in SNAPSHOTS:
        p = run(argv + [W, E])
        if p.returncode not in allowed:
            print("FAIL %s: exit %d not in %s\n%s%s" % (name, p.returncode, allowed, p.stdout, p.stderr), file=sys.stderr)
            return 1
        with open(os.path.join(SNAP, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(p.stdout)
        print("ok %s (exit %d)" % (name, p.returncode))
    return 0


def check():
    ok = True
    for path, text in ((W, WEIGHTS_TSV), (E, EVENTS_TSV)):
        have = open(path, encoding="utf-8").read()
        if have != text:
            print("DRIFT %s: ledger file does not match embedded constant (rerun build_examples.py)" % os.path.basename(path), file=sys.stderr)
            ok = False
    for name, argv, _allowed in SNAPSHOTS:
        p = run(argv + [W, E])
        path = os.path.join(SNAP, name + ".txt")
        if not os.path.exists(path):
            print("MISSING %s" % name, file=sys.stderr)
            ok = False
            continue
        want = open(path, encoding="utf-8").read()
        if p.stdout != want:
            print("DRIFT %s: snapshot is stale (rerun build_examples.py)" % name, file=sys.stderr)
            ok = False
    print("snapshots byte-identical" if ok else "snapshot drift detected", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else build())
