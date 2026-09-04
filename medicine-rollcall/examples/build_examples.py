#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the medicine-rollcall example ledger and snapshots.

The demo is 小陈's family medicine cabinet (as-of 2026-09-04, pinned):
23 boxes — 10 READY, 3 LOW, 4 OPENED_OUT, 6 EXPIRED. Readiness 43.5%,
below the 50% line (report exit 4).

Where the drama lives:
  布洛芬混悬液   packaging clock alive to 2027-06, in-use clock dead
                since 2026-04-13 (opened 03-14 + 30d syrup rule) —
                night fever --who kid = BARE: the child column is wiped out
                (the suppository expired 2025-12 and lives in the bathroom).
  wound         all three disinfectants dead (2 by in-use clock, 1 expired),
                bandaids don't disinfect — coverage exit 4.
  感灵颗粒 ×4   double-eleven hoard; 3 of 4 alive boxes expire inside the
                90-day window (hoard exit 4: an assembly line to the trash).
  左西替利嗪滴剂 in-use clock has 2 days left — next week's flip.
  simulate 90d  readiness 43.5% → 26.1%; the cabinet is an hourglass.

All snapshots are rendered with an explicit --as-of: the same ledger
reproduces byte-for-byte on any machine, any clock.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "medicine_rollcall.py")
LEDGER = os.path.join(HERE, "medicine_cabinet.tsv")
AS_OF = "2026-09-04"

LEDGER_TEXT = """\
# 家庭药箱库存快照 · name/role/form/kids/qty/unit/expiry/opened/location/open_days/note
# role: antipyretic退烧止痛 antidiarrheal腹泻肠胃 disinfectant外伤消毒
#       antihistamine抗过敏 dressing敷料辅助 supplement补剂 other
# form: blister铝箔袋装(无开封钟) bottle瓶装片剂180d syrup糖浆混悬30d
#       eyedrops眼药水28d cream软膏180d iodine碘伏30d suppository栓剂30d
#       lozenge含片泡腾90d spray喷雾90d other90d
# kids: y=儿童剂型   opened: 开封日(开封钟起点,可空)   open_days: 说明书口径,覆盖默认
# qty: 剩余使用单位(≤3 = LOW)   快照自报,工具不扫药箱
name	role	form	kids	qty	unit	expiry	opened	location	open_days	note
布洛芬混悬液	antipyretic	syrup	y	35	ml	2027-06-30	2026-03-14	浴室镜柜		儿童退烧主力，3月发烧那次开的
对乙酰氨基酚片	antipyretic	bottle	n	12	片	2026-12-31	2025-11-02	卧室抽屉		大人备用
布洛芬缓释胶囊	antipyretic	blister	n	18	粒	2028-06-30		卧室抽屉		没开过
退热栓	antipyretic	suppository	y	4	枚	2025-12-31		浴室镜柜		怕孩子喂药难备的
感冒灵颗粒	other	blister	n	9	袋	2026-11-15		玄关柜		双十一囤1
感冒灵颗粒	other	blister	n	9	袋	2026-11-15		玄关柜		双十一囤2
感冒灵颗粒	other	blister	n	2	袋	2026-11-15		玄关柜		上次感冒剩下的
感冒灵颗粒	other	blister	n	10	袋	2027-01-31		玄关柜		双十一囤3
蒙脱石散	antidiarrheal	blister	n	10	袋	2026-09-20		玄关柜		旅行剩的
蒙脱石散	antidiarrheal	blister	n	2	袋	2027-02-28		玄关柜		上次腹泻剩的
口服补液盐Ⅲ	antidiarrheal	blister	n	12	袋	2027-03-31		玄关柜		孩子腹泻脱水用
碘伏消毒液	disinfectant	iodine	n	45	ml	2027-08-31	2025-06-30	玄关柜		开封一年多没换过
酒精棉片	disinfectant	blister	n	40	片	2026-05-31		玄关柜		外卖凑单买的
双氧水	disinfectant	other	n	100	ml	2026-10-31	2026-05-01	玄关柜		上次磕破膝盖买的
创可贴	dressing	blister	n	2	贴	2026-12-31		玄关柜		就剩两贴了
氯雷他定片	antihistamine	blister	n	6	片	2027-10-31		卧室抽屉		花粉季买的
左西替利嗪滴剂	antihistamine	eyedrops	y	8	支	2027-04-30	2026-08-09	卧室抽屉		儿童抗过敏
玻璃酸钠滴眼液	other	eyedrops	n	10	支	2026-08-01	2026-02-01	卧室抽屉		干眼症用的
阿莫西林胶囊	other	blister	n	24	粒	2023-06-30		箱底		2021年体检剩的
藿香正气水	other	syrup	n	10	支	2026-06-30		玄关柜		夏天备的
维生素C泡腾片	supplement	lozenge	n	3	粒	2026-06-30	2025-12-01	浴室镜柜		囤货
碳酸钙D3片	supplement	bottle	n	60	片	2027-12-31	2026-07-01	卧室抽屉		补钙
炉甘石洗剂	other	cream	n	45	ml	2027-09-30		卧室抽屉		蚊子包用
"""

# (snapshot file, argv tail after ledger path)
SNAPSHOTS = [
    ("sample-report.txt", ["report", "--as-of", AS_OF]),
    ("sample-rollcall.txt", ["rollcall", "--as-of", AS_OF]),
    ("sample-night-fever-kid.txt",
     ["night", "--scene", "fever", "--who", "kid", "--as-of", AS_OF]),
    ("sample-night-wound.txt",
     ["night", "--scene", "wound", "--as-of", AS_OF]),
    ("sample-coverage.txt", ["coverage", "--as-of", AS_OF]),
    ("sample-hoard.txt", ["hoard", "--as-of", AS_OF]),
    ("sample-stash.txt", ["stash"]),
    ("sample-simulate.txt", ["simulate", "--days", "90", "--as-of", AS_OF]),
    ("sample-validate.txt", ["validate", "--as-of", AS_OF]),
]


def render() -> "list[tuple[str, str, int]]":
    out = []
    for fname, argv in SNAPSHOTS:
        proc = subprocess.run(
            [sys.executable, CLI] + argv + [LEDGER],
            capture_output=True, text=True)
        text = proc.stdout
        if proc.stderr:
            text += proc.stderr
        out.append((fname, text, proc.returncode))
    return out


def main() -> int:
    check = "--check" in sys.argv
    if check:
        if not os.path.exists(LEDGER):
            print("ledger missing; run without --check first")
            return 1
    else:
        with open(LEDGER, "w", encoding="utf-8") as f:
            f.write(LEDGER_TEXT)
    failures = 0
    for fname, text, code in render():
        path = os.path.join(HERE, fname)
        if check:
            with open(path, "r", encoding="utf-8") as f:
                want = f.read()
            if want != text:
                failures += 1
                print(f"MISMATCH {fname} (exit {code})")
                continue
            print(f"ok {fname} (exit {code})")
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"wrote {fname} (exit {code})")
    if check and failures:
        print(f"{failures} snapshot(s) drifted; regenerate in place")
        return 1
    print("byte-exact" if check else "built")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
