#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digital-attic · 数字阁楼 —— 媒体库人口普查.

问题：拍摄成本趋近于零、删除成本（决策痛）居高不下，于是媒体库只进不出、
单调膨胀，而「存储空间不足」是它唯一递达的账单——系统只在爆满时说话，
且只给一个「管理存储空间」按钮，从不给结构。3000 张截图、几十簇连拍废片、
几百张聊天缓存图和真正的回忆混在一起，看起来一样、权重一样；视频少而重、
占着大头房租，排序却只按时间不按体积；「存进去 = 再也不看」无人量化，
但每 GB 的房租照付。相册在这个时代悄悄从「记忆的仓库」变成了
「记忆的填埋场」——埋进去的东西不再被挖出，占地费照收。

digital-attic 把媒体库当成一个国家做人口普查。账本是一份可手编的 TSV
（name/path/bytes/birth/mtime/source），通常由 `scan` 从目录直接抄录：

  * scan      目录普查登记：抄录媒体文件，出生日期优先从文件名考古
              （IMG_20230521、Screenshot 2026-01-05、截屏20260105、
              WX20260105、VID_20250214、微信图片_20231102……），
              文件自己记得自己是哪天生的；考古不出才用 mtime 兜底并标注
  * census    全库普查报告：出生登记来源、库龄（按件中位 vs 按字节中位）、
              身份构成、只进不出（近 12 个月 vs 前一年新增）、垃圾三匠、
              房租账；垃圾件数过半或垃圾字节超 30% → exit 4
  * pyramid   库龄金字塔：按出生年分层，件数为高度——库长什么样一眼可见
  * junk      垃圾三匠明细：截图 / 连拍与成批 / 聊天缓存，字节贡献分解，
              加总恒等于总字节（一个字节不多不少）
  * rent      房租账：--price 月费 --quota 套餐容量 → 每 GB 月单价，
              总租 / 垃圾租 / 视频租逐年分解；不给套餐就不发明单价
  * simulate  瘦身推演：--prune junk|screenshots|bursts|chats|videos|aged
              --years N → 能省多少件、多少字节、多少房租、中位库龄怎么变；
              账本只算术，永不执行删除
  * validate  账本体检：出生来源占比（mtime 兜底过多 = 库龄是估的）、
              重复登记、寄居户披露

判决门禁：垃圾件数占比 > 50% 或垃圾字节占比 > 30% → RED（exit 4）。
两把尺子分开量——垃圾通常按件数是多数、按字节是少数（截图小而多），
视频则相反（少而重）；只量一把就会得出「删垃圾省不了几个钱」或
「全是视频的错」这类半截结论。

诚实条款：普查数库存结构，不读心——atime 不可靠，本件永不假装知道
你看过哪些照片；mtime 兜底的库龄在文件被拷贝/迁移时会失真，所以
账本记下每个出生日期的来源；重复照片检测需要读内容，超出普查范围；
aged ≠ 该删——老照片往往是唯一的孤本。删与不删，永远是人的决定。

零依赖：Python 3.8+ 标准库。账本是纯文本，一切留在本地。
「今天」默认真实当下，`--today` 钉死即逐字节可复现。

用法：
  python3 digital_attic.py scan ~/Pictures -o attic.tsv
  python3 digital_attic.py census attic.tsv --today 2026-09-01
  python3 digital_attic.py pyramid attic.tsv
  python3 digital_attic.py junk attic.tsv --today 2026-09-01
  python3 digital_attic.py rent attic.tsv --price 21 --quota 200
  python3 digital_attic.py simulate attic.tsv --prune junk
  python3 digital_attic.py validate attic.tsv

Exit codes:
  0  report produced（含绿灯）
  2  usage error / 账本缺失 / 坏行 / 未来出生日期 / 重复登记
  3  refusal: 目录不存在或零媒体 / 账本不足 30 件（THIN 拒绝普查结论）/
     推演口径缺参或空手而归
  4  gate: 垃圾件数占比 > 50% 或垃圾字节占比 > 30%
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from collections import Counter, OrderedDict
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量与口径
# ---------------------------------------------------------------------------

GB = 1e9                     # 与云存储计费口径一致：GB = 10⁹ 字节
MIN_FILES = 30               # 不足 30 件不开庭——小库不需要统计学
GATE_COUNT = 0.50            # 垃圾件数占比门禁：过半
GATE_BYTES = 0.30            # 垃圾字节占比门禁：三成
AGED_DEFAULT_YEARS = 5

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp",
             ".bmp", ".tif", ".tiff", ".dng", ".cr2", ".cr3", ".nef",
             ".arw", ".orf", ".rw2", ".raf"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp",
             ".mts", ".wmv", ".flv"}

# 身份判定优先级：screenshot > chat > burst（仅图片，需全库互查）> video > photo
# 每个文件有且仅有一个主身份 → 字节贡献分解加总恒等于总字节。
JUNK_IDS = ("screenshot", "burst", "chat")
ALL_IDS = ("photo", "video") + JUNK_IDS

ID_LABEL = {
    "photo": "照片",
    "video": "视频",
    "screenshot": "截图",
    "burst": "连拍/成批",
    "chat": "聊天缓存",
}

# ---------------------------------------------------------------------------
# 出生日期考古：文件自己记得自己是哪天生的
# ---------------------------------------------------------------------------

# 第一个 20xx 开头的紧凑日期串：20230521 / 2023-05-21 / 2023_05_21 / 2023.05.21
# re.search 从左向右，IMG_20230521_202000 里的时间串（20 开头）不会抢先。
_DATE_RE = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})")

# 截图家族（macOS/Android/Windows 中文/微信截屏/录屏），名字即身份
_SCREENSHOT_RE = re.compile(
    r"screenshot|screen_?shot|screen_?cap|screencapture|screen[ _-]recording"
    r"|截屏|屏幕截图|屏幕快照|录屏",
    re.IGNORECASE)
# ^WX + 8 位日期 = macOS 微信截屏（WX20260105-091233）
_WX_SHOT_RE = re.compile(r"^wx(20\d{2})\d{4}", re.IGNORECASE)
# 聊天工具缓存
_CHAT_RE = re.compile(
    r"微信图片|微信视频|wechat|weixin|mmexport|wximg", re.IGNORECASE)


def parse_name_date(name: str) -> Optional[dt.date]:
    """从文件名里考古出生日期；考古不出返回 None。"""
    m = _DATE_RE.search(name)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d)
    except ValueError:      # 20231332 这类：数字长得像日期但不是日期
        return None


def classify_base(name: str) -> str:
    """单文件身份（不含 burst——它需要全库互查）。"""
    stem, ext = os.path.splitext(name)
    if _SCREENSHOT_RE.search(stem) or _WX_SHOT_RE.match(stem):
        return "screenshot"
    if _CHAT_RE.search(stem):
        return "chat"
    if ext.lower() in VIDEO_EXT:
        return "video"
    return "photo"


def burst_group_key(item: "Item") -> Optional[Tuple[str, str, dt.date]]:
    """连拍/成批的分组键：同目录 + 同名基 + 同一天。

    账本的 birth 只有日期粒度，「同一分钟」在账本路径上不可得——
    但连拍的指纹不丢：同一批的文件名尾部序号是**秒级连续**的
    （IMG_…143022001 → 002 → 003），而一天里随手拍的多张
    （…143022 → …190512）序号跳变巨大。分组只圈范围，
    连续游程（相邻差 ≤ 60）才是定簇的证据，见 burst_clusters()。
    """
    stem = os.path.splitext(item.name)[0]
    base = re.sub(r"[\s_\-]*\d+$", "", stem)      # 去掉结尾的一段数字
    if base == stem or item.birth is None:        # 无尾号/无日期，无从成批
        return None
    return (item.path, base, item.birth)


BURST_STEP = 60        # 序号相邻差 ≤ 60 视为秒级连续（跨分钟连拍会被拆散——宁漏报不误报）
BURST_MIN = 3          # 游程 ≥ 3 张才成簇；两张相似是生活，三张相似才是连拍


def burst_clusters(items: List[Item]) -> set:
    """按分组键圈范围，组内按尾部序号找连续游程；返回 burst 成员的 id() 集。"""
    groups: Dict[Tuple[str, str, dt.date], List[Item]] = {}
    for it in items:
        k = burst_group_key(it)
        if k is not None:
            groups.setdefault(k, []).append(it)
    members: set = set()
    for group in groups.values():
        if len(group) < BURST_MIN:
            continue
        tagged = []
        for it in group:
            m = re.search(r"(\d+)$", os.path.splitext(it.name)[0])
            if not m:
                continue
            tagged.append((int(m.group(1)), it))
        tagged.sort(key=lambda x: x[0])
        run: List[Tuple[int, Item]] = []
        for num, it in tagged:
            if run and num - run[-1][0] > BURST_STEP:
                run = []
            run.append((num, it))
            if len(run) >= BURST_MIN:
                members.update(id(x) for _, x in run[-BURST_MIN:])
    return members


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------

class Item:
    __slots__ = ("name", "path", "bytes", "birth", "mtime", "source", "id")

    def __init__(self, name, path, size, birth, mtime, source, ident):
        self.name = name
        self.path = path
        self.bytes = size
        self.birth = birth
        self.mtime = mtime
        self.source = source
        self.id = ident


class Library:
    """账本加载 + 全库互查分类 + 汇总。"""

    def __init__(self, items: List[Item]):
        self.items = items
        self.total_bytes = sum(it.bytes for it in items)
        self.by_id_bytes: Dict[str, int] = {k: 0 for k in ALL_IDS}
        self.by_id_count: Dict[str, int] = {k: 0 for k in ALL_IDS}
        # 第二遍：burst 互查——只有 photo 身份的图片参与成批
        bursts = burst_clusters([it for it in items if it.id == "photo"])
        for it in items:
            if it.id == "photo" and id(it) in bursts:
                it.id = "burst"
            self.by_id_bytes[it.id] += it.bytes
            self.by_id_count[it.id] += 1
        self.junk_bytes = sum(self.by_id_bytes[j] for j in JUNK_IDS)
        self.junk_count = sum(self.by_id_count[j] for j in JUNK_IDS)

    @property
    def n(self) -> int:
        return len(self.items)


# 库龄需要 today，做成模块级可注入状态，避免把 today 穿过每一层签名。
_TODAY: dt.date = dt.date.today()


def set_today(today: dt.date) -> None:
    global _TODAY
    _TODAY = today


def _age_days(birth: dt.date) -> float:
    return (_TODAY - birth).days


def fmt_gb(n_bytes: int, digits: int = 1) -> str:
    if n_bytes >= GB:
        return f"{n_bytes / GB:.{digits}f} GB"
    return f"{n_bytes / 1e6:.0f} MB"


def fmt_int(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------
# 账本读写
# ---------------------------------------------------------------------------

COLUMNS = ("name", "path", "bytes", "birth", "mtime", "source")
VALID_SOURCES = ("name", "mtime")


def load_ledger(path: str, today: dt.date) -> Tuple[List[Item], List[str]]:
    """读账本。返回 (items, warnings)；坏行 raise LedgerError（exit 2）。"""
    rows: List[Item] = []
    warnings: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            cols = line.split("\t")
            if (len(cols) >= 3 and cols[0].strip().lower() == "name"
                    and cols[2].strip().lower() == "bytes"):
                continue        # 表头行（scan 产物自带；手编可有可无）
            if not (3 <= len(cols) <= 6):
                raise LedgerError(
                    f"第 {lineno} 行有 {len(cols)} 列（应为 3-6 列）：{line[:60]}")
            name = cols[0].strip()
            path = cols[1].strip() if len(cols) > 1 and cols[1].strip() else "."
            size_s = cols[2].strip()
            birth_s = cols[3].strip() if len(cols) > 3 else ""
            mtime_s = cols[4].strip() if len(cols) > 4 else ""
            source = cols[5].strip().lower() if len(cols) > 5 and cols[5].strip() else ""
            if not name:
                raise LedgerError(f"第 {lineno} 行 name 为空")
            try:
                size = int(size_s)
            except ValueError:
                raise LedgerError(f"第 {lineno} 行 bytes 不是整数：{size_s}")
            if size < 0:
                raise LedgerError(f"第 {lineno} 行 bytes 为负：{size}")
            if not birth_s or birth_s == "-":
                raise LedgerError(f"第 {lineno} 行缺出生日期 birth")
            try:
                birth = dt.date.fromisoformat(birth_s)
            except ValueError:
                raise LedgerError(f"第 {lineno} 行 birth 不是合法日期：{birth_s}")
            if birth > today:
                raise LedgerError(f"第 {lineno} 行出生日期在未来：{birth_s}（今天 {today}）")
            mtime = None
            if mtime_s and mtime_s != "-":
                try:
                    mtime = dt.date.fromisoformat(mtime_s)
                except ValueError:
                    raise LedgerError(f"第 {lineno} 行 mtime 不是合法日期：{mtime_s}")
            if source not in VALID_SOURCES:
                if source == "":
                    source = "name"     # 手编账本通常文件名自带日期；scan 永远写明
                else:
                    raise LedgerError(
                        f"第 {lineno} 行 source 只允许 name/mtime：{source}")
            key = (path, name)
            if key in seen:
                raise LedgerError(f"第 {lineno} 行重复登记：{path}{name}")
            seen.add(key)
            ident = classify_base(name)
            rows.append(Item(name, path, size, birth, mtime, source, ident))
    return rows, warnings


class LedgerError(Exception):
    pass


def scan_dir(root: str) -> Tuple[List[Item], Counter]:
    """扫描目录抄录账本。返回 (items, 寄居户扩展名计数)。"""
    root = os.path.abspath(root)
    items: List[Item] = []
    squatters: Counter = Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in IMAGE_EXT and ext not in VIDEO_EXT:
                squatters[ext or "(无扩展名)"] += 1
                continue
            try:
                size = os.path.getsize(full)
                mtime_dt = dt.date.fromtimestamp(os.path.getmtime(full))
            except OSError:
                continue
            rel = os.path.relpath(dirpath, root)
            birth = parse_name_date(fn)
            source = "name"
            if birth is None:
                birth = mtime_dt
                source = "mtime"
            items.append(Item(fn, rel if rel != "." else ".", size,
                              birth, mtime_dt, source, classify_base(fn)))
    return items, squatters


# ---------------------------------------------------------------------------
# 报告部件
# ---------------------------------------------------------------------------

def median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    if not s:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def library_median_age(lib: Library, subset: Optional[List[Item]] = None,
                       by_bytes: bool = False) -> float:
    pool = subset if subset is not None else lib.items
    if not pool:
        return 0.0
    if by_bytes:
        total = sum(it.bytes for it in pool)
        if total == 0:
            return 0.0
        acc = 0
        for it in sorted(pool, key=lambda x: x.birth):
            acc += it.bytes
            if acc * 2 >= total:
                return _age_days(it.birth)
        return _age_days(pool[-1].birth)
    return median([_age_days(it.birth) for it in pool])


def yearly_counts(lib: Library) -> "OrderedDict[int, Tuple[int, int]]":
    out: "OrderedDict[int, Tuple[int, int]]" = OrderedDict()
    for it in sorted(lib.items, key=lambda x: x.birth):
        y = it.birth.year
        c, b = out.get(y, (0, 0))
        out[y] = (c + 1, b + it.bytes)
    return out


def growth_line(lib: Library, today: dt.date) -> Optional[str]:
    """只进不出：近 12 个月 vs 前一年新增件数。账龄不足两年不判。"""
    births = [it.birth for it in lib.items]
    oldest, newest = min(births), max(births)
    if (newest - oldest).days < 730:
        return None
    lo1, hi1 = today - dt.timedelta(days=365), today
    lo0, hi0 = today - dt.timedelta(days=730), lo1
    n1 = sum(1 for b in births if lo1 <= b < hi1)
    n0 = sum(1 for b in births if lo0 <= b < hi0)
    if n0 == 0:
        return f"近 12 个月新增 {fmt_int(n1)} 件，前一年 0 件——库在加速生长"
    pct = (n1 - n0) / n0 * 100.0
    if pct > 10:
        word = "加速"
    elif pct < -10:
        word = "放缓"
    else:
        word = "匀速"   # 匀速也照样爆：只进不出，增长率再平也是单调膨胀
    return (f"近 12 个月新增 {fmt_int(n1)} 件，前一年 {fmt_int(n0)} 件"
            f"（{pct:+.1f}%）——库在{word}生长；删除行为不在普查视野里，"
            "只进不出是默认命运")


def unit_price(price: float, quota: float) -> float:
    """每 GB 每月单价（元）。"""
    if quota <= 0:
        raise ValueError("quota 必须为正")
    return price / quota


# ---------------------------------------------------------------------------
# 命令：census
# ---------------------------------------------------------------------------

def census_report(lib: Library, today: dt.date,
                  price: Optional[float], quota: Optional[float]) -> List[str]:
    lines: List[str] = []
    span_lo = min(it.birth for it in lib.items)
    span_hi = max(it.birth for it in lib.items)
    lines.append(
        f"数字阁楼普查 · {fmt_int(lib.n)} 件 · {fmt_gb(lib.total_bytes)}"
        f"（{span_lo} → {span_hi}）")
    lines.append("")

    n_name = sum(1 for it in lib.items if it.source == "name")
    lines.append(
        f"  出生登记      文件名考古 {fmt_int(n_name)} 件"
        f"（{n_name / lib.n * 100:.1f}%）· 时间戳兜底 {fmt_int(lib.n - n_name)} 件"
        f"（{(lib.n - n_name) / lib.n * 100:.1f}%）")

    age_c = library_median_age(lib)
    age_b = library_median_age(lib, by_bytes=True)
    word = "新的重，老的轻" if age_b < age_c else "老的也重"
    lines.append(
        f"  库龄          按件数中位 {age_c / 365.25:.1f} 年 · "
        f"按字节中位 {age_b / 365.25:.1f} 年——{word}")

    id_counts = " / ".join(
        f"{ID_LABEL[k]} {fmt_int(lib.by_id_count[k])}" for k in ALL_IDS)
    id_bytes = " / ".join(
        f"{ID_LABEL[k]} {fmt_gb(lib.by_id_bytes[k])}" for k in ALL_IDS)
    lines.append(f"  身份构成      {id_counts}")
    lines.append(f"                字节  {id_bytes}")

    g = growth_line(lib, today)
    if g:
        lines.append(f"  只进不出      {g}")
    else:
        lines.append("  只进不出      账龄不足两年，增速免判")

    junk_c_ratio = lib.junk_count / lib.n
    junk_b_ratio = (lib.junk_bytes / lib.total_bytes) if lib.total_bytes else 0.0
    parts = []
    for jid in JUNK_IDS:
        parts.append(f"{ID_LABEL[jid]} {fmt_int(lib.by_id_count[jid])} 件"
                     f" {fmt_gb(lib.by_id_bytes[jid])}")
    lines.append(f"  垃圾三匠      {' · '.join(parts)}")
    lines.append(
        f"                合计 {fmt_int(lib.junk_count)} 件"
        f"（{junk_c_ratio * 100:.1f}% 件数）· {fmt_gb(lib.junk_bytes)}"
        f"（{junk_b_ratio * 100:.1f}% 字节）")
    if junk_c_ratio > junk_b_ratio + 0.05:
        lines.append(
            "                件数口径是多数、字节口径是少数：删垃圾省不下房租，"
            "省的是每一次翻找")
    elif junk_b_ratio > junk_c_ratio + 0.05:
        lines.append(
            "                字节口径是多数、件数口径是少数：大头藏在重的里面，"
            "别只盯着小图快删")

    if price is not None and quota is not None:
        up = unit_price(price, quota)
        monthly = lib.total_bytes / GB * up
        junk_m = lib.junk_bytes / GB * up
        vid_m = lib.by_id_bytes["video"] / GB * up
        vid_share = vid_m / monthly * 100 if monthly else 0.0
        lines.append(
            f"  房租          {lib.total_bytes / GB:.1f} GB × "
            f"{up:.4f} 元/GB/月（¥{price:g} ÷ {quota:g} GB）"
            f"= ¥{monthly:.2f}/月 · ¥{monthly * 12:.1f}/年")
        lines.append(
            f"                其中垃圾房租 ¥{junk_m:.2f}/月 · "
            f"视频房租 ¥{vid_m:.2f}/月（{vid_share:.1f}%）")
    else:
        lines.append(
            "  房租          未给 --price/--quota，不发明单价（rent 命令可补算）")

    lines.append("")
    # 门禁
    if junk_c_ratio > GATE_COUNT:
        lines.append(
            f"判定 RED —— 垃圾件数占比 {junk_c_ratio * 100:.1f}% 过半"
            f"（门禁 {GATE_COUNT * 100:.0f}%）：这半个库的每次翻找都在陪跑；"
            "junk 看明细，simulate 算推演，删与不删仍是人的决定")
    elif junk_b_ratio > GATE_BYTES:
        lines.append(
            f"判定 RED —— 垃圾字节占比 {junk_b_ratio * 100:.1f}% 超三成"
            f"（门禁 {GATE_BYTES * 100:.0f}%）：大头在重的里面")
    else:
        lines.append(
            f"判定 GREEN —— 垃圾件数 {junk_c_ratio * 100:.1f}% 未过半、"
            f"字节 {junk_b_ratio * 100:.1f}% 未超三成：库存结构尚可，继续普查金字塔")
    return lines


# ---------------------------------------------------------------------------
# 命令：pyramid
# ---------------------------------------------------------------------------

def pyramid_report(lib: Library) -> List[str]:
    lines: List[str] = []
    lines.append(f"库龄金字塔 · {fmt_int(lib.n)} 件 · 条长 = 件数")
    lines.append("")
    years = yearly_counts(lib)
    max_c = max(c for c, _ in years.values()) or 1
    for y, (c, b) in years.items():
        bar = "█" * max(1, round(c / max_c * 36))
        lines.append(f"  {y}  {bar}  {fmt_int(c)} 件 · {fmt_gb(b)}")
    lines.append("")
    age_c = library_median_age(lib)
    age_b = library_median_age(lib, by_bytes=True)
    lines.append(
        f"  按件数中位库龄 {age_c / 365.25:.1f} 年 · "
        f"按字节中位库龄 {age_b / 365.25:.1f} 年")
    if age_b < age_c - 0.25 * 365.25:
        lines.append(
            "  字节比件数年轻：新近的最重（往往是视频）——库在变重，不在变老")
    elif age_b > age_c + 0.25 * 365.25:
        lines.append(
            "  字节比件数年老：老照片反而最重（扫描件/原图）——阁楼的地基在最底层")
    else:
        lines.append("  两把尺子基本一致：库的重量与年龄同步")
    return lines


# ---------------------------------------------------------------------------
# 命令：junk
# ---------------------------------------------------------------------------

def junk_report(lib: Library, today: dt.date) -> List[str]:
    lines: List[str] = []
    lines.append(f"垃圾三匠 · 截图 / 连拍与成批 / 聊天缓存")
    lines.append("")
    for jid in JUNK_IDS:
        c, b = lib.by_id_count[jid], lib.by_id_bytes[jid]
        share_c = c / lib.n * 100 if lib.n else 0.0
        share_b = b / lib.total_bytes * 100 if lib.total_bytes else 0.0
        sub = [it for it in lib.items if it.id == jid]
        age = library_median_age(lib, subset=sub) if sub else 0.0
        lines.append(
            f"  {ID_LABEL[jid]:<6} {fmt_int(c)} 件（{share_c:.1f}% 件数）· "
            f"{fmt_gb(b)}（{share_b:.1f}% 字节）· 中位库龄 {age / 365.25:.1f} 年")
    total_c_share = lib.junk_count / lib.n * 100 if lib.n else 0.0
    total_b_share = (lib.junk_bytes / lib.total_bytes * 100
                     if lib.total_bytes else 0.0)
    lines.append("")
    lines.append(
        f"  合计 {fmt_int(lib.junk_count)} 件（{total_c_share:.1f}% 件数）"
        f" · {fmt_gb(lib.junk_bytes)}（{total_b_share:.1f}% 字节）")
    # 字节恒等式：五类身份加总 = 总字节
    ident_sum = sum(lib.by_id_bytes[k] for k in ALL_IDS)
    lines.append(
        f"  恒等式  五类身份字节加总 = 总字节：{fmt_int(ident_sum)} = "
        f"{fmt_int(lib.total_bytes)}（残差 {ident_sum - lib.total_bytes}）")
    if total_c_share > GATE_COUNT * 100:
        lines.append(
            f"  判定 RED —— 按件数过半是垃圾：这不是收藏，是囤积（exit 4）")
    elif total_b_share > GATE_BYTES * 100:
        lines.append(
            f"  判定 RED —— 垃圾字节超三成：大头在重的里面（exit 4）")
    else:
        lines.append("  判定 GREEN —— 双口径均未越门禁")
    return lines


# ---------------------------------------------------------------------------
# 命令：rent
# ---------------------------------------------------------------------------

def rent_report(lib: Library, price: float, quota: float) -> List[str]:
    lines: List[str] = []
    up = unit_price(price, quota)
    monthly = lib.total_bytes / GB * up
    lines.append(
        f"房租账 · {lib.total_bytes / GB:.1f} GB × {up:.4f} 元/GB/月"
        f"（¥{price:g} ÷ {quota:g} GB）")
    if lib.total_bytes / GB > quota:
        lines.append(
            f"  横幅          库已超你给的 {quota:g} GB 档——实际计费是档位制，"
            "这里的单价线性外推只作量级参考；请用你实际订阅的那档")
    lines.append("")
    rows = [(k, lib.by_id_bytes[k]) for k in ALL_IDS if lib.by_id_bytes[k] > 0]
    rows.sort(key=lambda kv: -kv[1])
    for k, b in rows:
        m = b / GB * up
        share = m / monthly * 100 if monthly else 0.0
        lines.append(
            f"  {ID_LABEL[k]:<6} {fmt_gb(b):>12}  ¥{m:6.2f}/月  "
            f"¥{m * 12:7.1f}/年  （{share:.1f}%）")
    lines.append("")
    junk_m = lib.junk_bytes / GB * up
    vid_m = lib.by_id_bytes["video"] / GB * up
    lines.append(
        f"  总租 ¥{monthly:.2f}/月（¥{monthly * 12:.1f}/年）· "
        f"垃圾租 ¥{junk_m:.2f}/月 · 视频租 ¥{vid_m:.2f}/月")
    if monthly < 5:
        lines.append(
            "  诚实条款：存储的钱是小头——真正的成本在每次翻找、备份与迁移的时间，"
            "房租账只是给『看不见的占用』一个标价")
    return lines


# ---------------------------------------------------------------------------
# 命令：simulate
# ---------------------------------------------------------------------------

def prune_subset(lib: Library, kind: str, years: int) -> Tuple[List[Item], str]:
    if kind == "junk":
        return [it for it in lib.items if it.id in JUNK_IDS], "垃圾三匠全部"
    if kind == "screenshots":
        return [it for it in lib.items if it.id == "screenshot"], "截图"
    if kind == "bursts":
        return [it for it in lib.items if it.id == "burst"], "连拍/成批"
    if kind == "chats":
        return [it for it in lib.items if it.id == "chat"], "聊天缓存"
    if kind == "videos":
        return [it for it in lib.items if it.id == "video"], "全部视频"
    if kind == "aged":
        cut = years * 365.25
        return ([it for it in lib.items if _age_days(it.birth) >= cut],
                f"库龄 ≥ {years} 年的全部")
    raise ValueError(f"未知口径 {kind}")


def simulate_report(lib: Library, kind: str, years: int,
                    price: Optional[float], quota: Optional[float]) -> List[str]:
    victims, label = prune_subset(lib, kind, years)
    lines: List[str] = []
    if not victims:
        lines.append(f"推演口径「{label}」在本库为空——没有可推演的对象（exit 3）")
        return lines
    v_bytes = sum(it.bytes for it in victims)
    vset = set(map(id, victims))
    survivors = [it for it in lib.items if id(it) not in vset]
    new_n = len(survivors)
    new_total = lib.total_bytes - v_bytes
    new_age = (median([_age_days(it.birth) for it in survivors])
               if survivors else 0.0)

    lines.append(
        f"瘦身推演 · 口径「{label}」：{fmt_int(len(victims))} 件 "
        f"{fmt_gb(v_bytes)} 出库")
    lines.append("")
    lines.append(
        f"  库存          {fmt_int(lib.n)} 件 {fmt_gb(lib.total_bytes)} → "
        f"{fmt_int(new_n)} 件 {fmt_gb(new_total)}"
        f"（省 {(v_bytes / lib.total_bytes * 100) if lib.total_bytes else 0:.1f}% 字节）")
    lines.append(
        f"  中位库龄      "
        f"{library_median_age(lib) / 365.25:.1f} 年 → {new_age / 365.25:.1f} 年")
    if price is not None and quota is not None:
        up = unit_price(price, quota)
        lines.append(
            f"  房租          ¥{lib.total_bytes / GB * up:.2f}/月 → "
            f"¥{new_total / GB * up:.2f}/月（省 ¥{v_bytes / GB * up:.2f}/月 · "
            f"¥{v_bytes / GB * up * 12:.1f}/年）")
    else:
        lines.append("  房租          未给 --price/--quota，只算字节不算钱")
    # 删完之后幸存库还红不红
    if new_n > 0:
        sj = sum(1 for it in survivors if it.id in JUNK_IDS)
        sjb = sum(it.bytes for it in survivors if it.id in JUNK_IDS)
        rc = sj / new_n
        rb = sjb / new_total if new_total else 0.0
        verdict = "RED" if (rc > GATE_COUNT or rb > GATE_BYTES) else "GREEN"
        lines.append(
            f"  幸存库体检    垃圾件数 {rc * 100:.1f}% · 字节 {rb * 100:.1f}% → {verdict}")
    if kind == "aged":
        lines.append(
            "  横幅：aged ≠ 该删——老照片往往是唯一的孤本，推演只是算术，不是建议")
    lines.append(
        "  账本只算术，永不执行删除；删与不删，永远是人的决定")
    return lines


# ---------------------------------------------------------------------------
# 命令：validate
# ---------------------------------------------------------------------------

def validate_report(lib: Library, today: dt.date) -> List[str]:
    lines: List[str] = []
    n_name = sum(1 for it in lib.items if it.source == "name")
    n_mtime = lib.n - n_name
    lines.append(f"账本体检 · {fmt_int(lib.n)} 件")
    lines.append("")
    lines.append(
        f"  出生来源      文件名考古 {fmt_int(n_name)} 件"
        f"（{n_name / lib.n * 100:.1f}%）· mtime 兜底 {fmt_int(n_mtime)} 件"
        f"（{n_mtime / lib.n * 100:.1f}%）")
    if n_mtime / lib.n > 0.3:
        lines.append(
            "  警告          mtime 兜底占比超三成：拷贝/迁移会重置文件时间戳，"
            "这部分库龄是估的——普查结论按『带误差』读")
    future_mt = [it for it in lib.items if it.mtime and it.mtime > today]
    if future_mt:
        lines.append(
            f"  披露          {len(future_mt)} 件 mtime 在今天之后"
            f"（系统时钟漂移？）——birth 已按账本记录为准")
    dup_stem = Counter(it.name for it in lib.items)
    dups = [n for n, c in dup_stem.items() if c > 1]
    if dups:
        lines.append(
            f"  披露          {len(dups)} 个同名文件在不同目录（如 {dups[0]}）——"
            "内容是否重复超出普查范围（不读文件内容）")
    big = max(lib.items, key=lambda it: it.bytes)
    lines.append(
        f"  最大单件      {big.name[:48]} · {fmt_gb(big.bytes)}"
        f"（占库 {big.bytes / lib.total_bytes * 100:.1f}%）")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="digital_attic.py",
        description="数字阁楼 · 媒体库人口普查（零依赖）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("ledger", help="账本 TSV（scan 产物或手编）")
        sp.add_argument("--today", default=None, help="钉死今天：YYYY-MM-DD")

    sp = sub.add_parser("scan", help="扫描目录抄录账本")
    sp.add_argument("root", help="媒体库根目录")
    sp.add_argument("-o", "--output", default=None,
                    help="输出 TSV 路径（默认 stdout）")

    sp = sub.add_parser("census", help="全库普查报告")
    add_common(sp)
    sp.add_argument("--price", type=float, default=None, help="套餐月费（元）")
    sp.add_argument("--quota", type=float, default=None, help="套餐容量（GB）")

    sp = sub.add_parser("pyramid", help="库龄金字塔")
    add_common(sp)

    sp = sub.add_parser("junk", help="垃圾三匠明细")
    add_common(sp)

    sp = sub.add_parser("rent", help="房租账")
    add_common(sp)
    sp.add_argument("--price", type=float, required=True, help="套餐月费（元）")
    sp.add_argument("--quota", type=float, required=True, help="套餐容量（GB）")

    sp = sub.add_parser("simulate", help="瘦身推演（永不执行删除）")
    add_common(sp)
    sp.add_argument("--prune", required=True,
                    choices=["junk", "screenshots", "bursts", "chats",
                             "videos", "aged"],
                    help="推演口径")
    sp.add_argument("--years", type=int, default=AGED_DEFAULT_YEARS,
                    help="aged 口径的库龄线（年，默认 5）")
    sp.add_argument("--price", type=float, default=None, help="套餐月费（元）")
    sp.add_argument("--quota", type=float, default=None, help="套餐容量（GB）")

    sp = sub.add_parser("validate", help="账本体检")
    add_common(sp)
    return p


def _parse_today(s: Optional[str]) -> dt.date:
    if not s:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise LedgerError(f"--today 不是合法日期：{s}")


def _load_or_die(args) -> Library:
    items, _ = load_ledger(args.ledger, _parse_today(getattr(args, "today", None)))
    return Library(items)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "scan":
        if not os.path.isdir(args.root):
            print(f"目录不存在：{args.root}", file=sys.stderr)
            return 3
        items, squatters = scan_dir(args.root)
        if not items:
            print("零媒体文件——这不是阁楼，是空房间", file=sys.stderr)
            return 3
        rows = ["\t".join(COLUMNS)]
        for it in sorted(items, key=lambda x: (x.birth, x.name)):
            rows.append("\t".join([
                it.name, it.path, str(it.bytes), it.birth.isoformat(),
                it.mtime.isoformat(), it.source]))
        out = "\n".join(rows) + "\n"
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(out)
            sq = sum(squatters.values())
            print(f"已登记 {fmt_int(len(items))} 件媒体 → {args.output}"
                  f"（寄居户 {sq} 个非媒体文件未入库）")
        else:
            sys.stdout.write(out)
            sq = sum(squatters.values())
            if sq:
                print(f"# 寄居户 {sq} 个非媒体文件未入库", file=sys.stderr)
        return 0

    if not getattr(args, "ledger", None):
        parser.error("需要账本路径")
    try:
        today = _parse_today(args.today)
        set_today(today)
        lib = _load_or_die(args)
    except LedgerError as e:
        print(f"账本错误：{e}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"账本不存在：{args.ledger}", file=sys.stderr)
        return 2

    if lib.n < MIN_FILES and args.cmd in ("census", "pyramid", "junk", "rent",
                                          "simulate"):
        print(f"账本仅 {lib.n} 件（不足 {MIN_FILES}）——"
              "这么小的库不需要普查统计学，肉眼即可（exit 3）", file=sys.stderr)
        return 3

    if args.cmd == "census":
        lines = census_report(lib, today, args.price, args.quota)
        gate = (lib.junk_count / lib.n > GATE_COUNT
                or (lib.total_bytes and lib.junk_bytes / lib.total_bytes > GATE_BYTES))
    elif args.cmd == "pyramid":
        lines = pyramid_report(lib)
        gate = False
    elif args.cmd == "junk":
        lines = junk_report(lib, today)
        gate = (lib.junk_count / lib.n > GATE_COUNT
                or (lib.total_bytes and lib.junk_bytes / lib.total_bytes > GATE_BYTES))
    elif args.cmd == "rent":
        lines = rent_report(lib, args.price, args.quota)
        gate = False
    elif args.cmd == "simulate":
        if args.prune == "aged" and args.years <= 0:
            print("--years 必须为正整数", file=sys.stderr)
            return 3
        lines = simulate_report(lib, args.prune, args.years,
                                args.price, args.quota)
        print("\n".join(lines))
        return 0 if "没有可推演的对象" not in lines[0] else 3
    elif args.cmd == "validate":
        lines = validate_report(lib, today)
        gate = False
    else:  # pragma: no cover
        parser.error(f"未知命令 {args.cmd}")

    print("\n".join(lines))
    return 4 if gate else 0


if __name__ == "__main__":
    sys.exit(main())
