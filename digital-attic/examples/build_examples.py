#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or verify) the digital-attic example ledger and report snapshots.

The demo attic is one person's 8 years of shooting (2019-06 to 2026-08):
1,277 items / ~278 GB. The script of this attic is the split between the
two rulers: by count, junk (screenshots + bursts + chat cache) is 660
items — more than half the library (RED, exit 4); by bytes, junk is
under 1% while 152 videos hold ~98% of the rent. Deleting junk saves
almost no rent but saves every scroll; the big landlord is video.

  python3 build_examples.py            # write ledger + regenerate snapshots
  python3 build_examples.py --check    # byte-exact CI verification, no writes

Determinism: no `random` module — a fixed-step LCG keeps every byte
stable across Python versions and machines.
"""

import os
import subprocess
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "digital_attic.py")
LEDGER = os.path.join(HERE, "attic.tsv")
TODAY = "2026-09-01"

# ---------------------------------------------------------------------------
# 确定性随机（LCG，跨版本字节稳定）
# ---------------------------------------------------------------------------

class Det:
    def __init__(self, seed: int):
        self.s = seed & ((1 << 64) - 1)

    def next(self) -> int:
        self.s = (self.s * 6364136223846793005 + 1442695040888963407) \
            & ((1 << 64) - 1)
        return self.s >> 11

    def randint(self, a: int, b: int) -> int:
        return a + self.next() % (b - a + 1)

    def choice(self, seq):
        return seq[self.next() % len(seq)]


R = Det(20260901)

# ---------------------------------------------------------------------------
# 逐年计划：每件的身份在生成时决定
# ---------------------------------------------------------------------------

# year -> (photo, n_burst_clusters, screenshot, chat, video)
#   burst 簇内 4-7 张同分钟连号，簇均 ~6 张
PLAN = {
    2019: (52, 2, 14, 2, 0),
    2020: (70, 3, 22, 4, 2),
    2021: (88, 4, 34, 8, 6),
    2022: (78, 5, 48, 14, 16),
    2023: (66, 6, 58, 18, 28),
    2024: (52, 7, 52, 16, 34),
    2025: (38, 8, 62, 16, 38),
    2026: (21, 5, 40, 12, 28),   # 2026-01 → 2026-08
}

def p_img(d, hh, mm, ss, seq):
    return f"IMG_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}{seq:03d}.jpg"

def p_wa(d, hh, mm, ss, seq):
    return f"IMG-{d:%Y%m%d}-WB{seq:04d}.jpg"

def p_pxl(d, hh, mm, ss, seq):
    return f"PXL_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}{seq:05d}.jpg"

def p_vlad(d, hh, mm, ss, seq):
    return f"{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}.jpg"

def p_dsc(d, hh, mm, ss, seq):     # 无日期名 → mtime 兜底（散拍，不成簇）
    return f"DSC_{seq:05d}.JPG"

def p_ios(d, hh, mm, ss, seq):     # 无日期名 → mtime 兜底（连号不同分钟）
    return f"IMG_{seq:04d}.HEIC"

def p_scr_mac(d, hh, mm, ss, seq):
    return f"Screenshot {d:%Y-%m-%d} at {hh:02d}.{mm:02d}.{ss:02d}.png"

def p_scr_and(d, hh, mm, ss, seq):
    return f"Screenshot_{d:%Y%m%d}-{hh:02d}{mm:02d}{ss:02d}.png"

def p_scr_cn(d, hh, mm, ss, seq):
    return f"截屏{d:%Y-%m-%d} {hh:02d}.{mm:02d}.{ss:02d}.png"

def p_scr_win(d, hh, mm, ss, seq):
    return f"屏幕截图 {d:%Y-%m-%d} {hh:02d}{mm:02d}{ss:02d}.png"

def p_scr_wx(d, hh, mm, ss, seq):
    return f"WX{d:%Y%m%d}-{hh:02d}{mm:02d}{ss:02d}.png"

def p_chat_cn(d, hh, mm, ss, seq):
    return f"微信图片_{d:%Y%m%d%H%M%S}.jpg"

def p_chat_en(d, hh, mm, ss, seq):
    return f"WeChat Image {d:%Y-%m-%d} {hh:02d}{mm:02d}{ss:02d}.jpg"

def p_chat_wximg(d, hh, mm, ss, seq):
    return f"WXIMG_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}.jpg"

def p_vid_and(d, hh, mm, ss, seq):
    return f"VID_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}.mp4"

def p_vid_pxl(d, hh, mm, ss, seq):
    return f"PXL_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}.TS.mp4"

def p_vid_mov(d, hh, mm, ss, seq):
    return f"VID_{d:%Y%m%d}_{hh:02d}{mm:02d}{ss:02d}.mov"

PHOTO_POOL = [p_img, p_wa, p_pxl, p_vlad]
SCR_POOL = [p_scr_mac, p_scr_and, p_scr_cn, p_scr_win, p_scr_wx]
CHAT_POOL = [p_chat_cn, p_chat_en, p_chat_wximg]
VID_POOL = [p_vid_and, p_vid_pxl, p_vid_mov]

# mtime 兜底的 12 件：6 件散拍（不同日不成簇）+ 6 件连号但分处不同分钟
MTIME_SCATTER = ["DSC_00001.JPG", "DSC_00002.JPG", "DSC_00003.JPG",
                 "IMG_0031.HEIC", "IMG_0032.HEIC", "IMG_0033.HEIC"]
MTIME_STAGGER = ["IMG_0101.HEIC", "IMG_0102.HEIC", "IMG_0103.HEIC",
                 "IMG_0104.HEIC", "IMG_0105.HEIC", "IMG_0106.HEIC"]
MTIME_DATES = [date(2019, 8, 14), date(2019, 10, 2), date(2020, 3, 21),
               date(2020, 11, 8), date(2021, 2, 15), date(2021, 6, 30),
               date(2020, 5, 9), date(2020, 5, 30), date(2020, 6, 19),
               date(2020, 7, 12), date(2020, 8, 3), date(2020, 9, 25)]


def photo_size(d: date, R: Det) -> int:
    """照片平均大小随年代线性增长（2.8MB → 4.8MB），抖动 ±30%。"""
    t = min(max((d - date(2019, 1, 1)).days / (366 * 7), 0.0), 1.0)
    base = 2.8e6 + t * 2.0e6
    return int(base * (0.7 + R.next() % 60 / 100.0))


def video_size(d: date, R: Det) -> int:
    """2022 前以 1080p 为主（~150MB）；2022 起进入 4K（0.8–3.2 GB）。"""
    if d < date(2022, 1, 1):
        return int((90e6 + R.next() % 140e6))
    return int(0.8e9 + R.next() % int(2.4e9))


def gen_items():
    items = []          # (name, path, bytes, birth_iso, mtime_iso, source)
    used_names = set()

    def emit(name, path, size, birth, source="name"):
        # 名字冲突时给 seq 换签（保持身份与日期不变）
        base, dot, ext = name.partition(".")
        while name in used_names:
            base = f"{base.rstrip('0123456789')}{'x' if not base.endswith('x') else 'xx'}"
            name = f"{base}.{ext}" if dot else base
        used_names.add(name)
        items.append((name, path, size, birth.isoformat(),
                      birth.isoformat(), source))

    for year, (n_photo, n_clusters, n_scr, n_chat, n_vid) in PLAN.items():
        last_month = 8 if year == 2026 else 12

        def a_date():
            m = R.randint(1, last_month)
            day = R.randint(1, {2: 28}.get(m, 30))
            return date(year, m, day)

        for _ in range(n_photo):
            d = a_date()
            hh, mm, ss = R.randint(7, 22), R.randint(0, 59), R.randint(0, 59)
            name = R.choice(PHOTO_POOL)(d, hh, mm, ss, R.randint(0, 99999))
            emit(name, f"{year}/", photo_size(d, R), d)

        # burst 簇：每簇 4-7 张，同一秒内连拍（真实相机命名：时间戳不动、
        # 尾部序号递增——尾部数字连续正是 burst 互查的指纹）
        for _ in range(n_clusters):
            d = a_date()
            hh, mm = R.randint(7, 22), R.randint(0, 59)
            ss = R.randint(0, 59)
            n = R.randint(4, 7)
            for k in range(n):
                name = p_img(d, hh, mm, ss, k + 1)
                emit(name, f"{year}/",
                     int(1.5e6 * (0.8 + R.next() % 40 / 100.0)), d)

        for _ in range(n_scr):
            d = a_date()
            name = R.choice(SCR_POOL)(d, R.randint(7, 23), R.randint(0, 59),
                                      R.randint(0, 59), 0)
            emit(name, f"{year}/Screenshots/" if year >= 2022 else f"{year}/",
                 int(0.6e6 + R.next() % int(1.9e6)), d)

        for _ in range(n_chat):
            d = a_date()
            name = R.choice(CHAT_POOL)(d, R.randint(7, 23), R.randint(0, 59),
                                       R.randint(0, 99), R.randint(0, 99))
            emit(name, f"{year}/", int(0.3e6 + R.next() % int(1.2e6)), d)

        for _ in range(n_vid):
            d = a_date()
            name = R.choice(VID_POOL)(d, R.randint(7, 22), R.randint(0, 59),
                                      R.randint(0, 59), 0)
            emit(name, f"{year}/", video_size(d, R), d)

    # mtime 兜底 12 件：散拍 6 件（不同日）+ 连号 6 件（同目录但分处不同分钟，
    # 结构上不成簇——burst 互查的对照组）
    for i, (name, d) in enumerate(zip(MTIME_SCATTER + MTIME_STAGGER,
                                      MTIME_DATES)):
        emit(name, "imported/", photo_size(d, R), d, source="mtime")

    items.sort(key=lambda r: (r[3], r[0]))
    return items


def write_ledger():
    rows = ["name\tpath\tbytes\tbirth\tmtime\tsource"]
    for name, path, size, birth, mtime, source in gen_items():
        rows.append(f"{name}\t{path}\t{size}\t{birth}\t{mtime}\t{source}")
    with open(LEDGER, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    return len(rows) - 1


SNAPSHOTS = [
    ("sample-census.txt",
     ["census", LEDGER, "--today", TODAY, "--price", "68", "--quota", "2048"]),
    ("sample-pyramid.txt", ["pyramid", LEDGER]),
    ("sample-junk.txt", ["junk", LEDGER, "--today", TODAY]),
    ("sample-rent.txt", ["rent", LEDGER, "--price", "68", "--quota", "2048"]),
    ("sample-simulate-junk.txt",
     ["simulate", LEDGER, "--prune", "junk", "--today", TODAY,
      "--price", "68", "--quota", "2048"]),
    ("sample-simulate-videos.txt",
     ["simulate", LEDGER, "--prune", "videos", "--today", TODAY,
      "--price", "68", "--quota", "2048"]),
    ("sample-simulate-aged.txt",
     ["simulate", LEDGER, "--prune", "aged", "--years", "5",
      "--today", TODAY]),
    ("sample-validate.txt", ["validate", LEDGER, "--today", TODAY]),
]


def run_snapshots(check: bool) -> int:
    ok = True
    for fname, argv in SNAPSHOTS:
        path = os.path.join(HERE, fname)
        proc = subprocess.run(
            [sys.executable, CLI] + argv,
            capture_output=True, text=True)
        out = proc.stdout
        if proc.returncode not in (0, 4):
            print(f"[FAIL] {' '.join(argv)} → exit {proc.returncode}\n{proc.stderr}")
            ok = False
            continue
        if check:
            if not os.path.exists(path):
                print(f"[FAIL] 缺少快照 {fname}——先不带 --check 跑一次")
                ok = False
                continue
            with open(path, "r", encoding="utf-8") as fh:
                want = fh.read()
            if want != out:
                print(f"[FAIL] 快照漂移：{fname}（exit {proc.returncode}）")
                import difflib
                for line in list(difflib.unified_diff(
                        want.splitlines(), out.splitlines(),
                        "want", "got", lineterm=""))[:40]:
                    print(line)
                ok = False
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
            print(f"[snap] {fname} (exit {proc.returncode})")
    return 0 if ok else 1


def main() -> int:
    if "--check" in sys.argv[1:]:
        if not os.path.exists(LEDGER):
            print("[FAIL] 账本不存在——先不带 --check 跑一次")
            return 1
        return run_snapshots(check=True)
    n = write_ledger()
    print(f"[ledger] attic.tsv · {n} 件")
    return run_snapshots(check=False)


if __name__ == "__main__":
    sys.exit(main())
