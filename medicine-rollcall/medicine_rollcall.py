#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""medicine-rollcall · 药箱点名 —— 家庭药箱战备审计.

药品有两口钟：包装效期钟印在盒上，开封效期钟只活在「好像刚开没多久」的
记忆里。本件把药箱当一本战备账本审计：

  双钟模型      可用截止 = min(包装效期, 开封日 + 开封效期)，blister 无开封钟；
  判决阶梯      EXPIRED > OPENED_OUT > LOW > READY（先判死，再判量）；
  场景矩阵      fever/gut/wound/allergy 四个半夜场景各自过闸，
                儿童剂型单独一栏 —— 孩子的药箱比大人的先阵亡；
  囤积质证      同名 >= 3 盒点名，组内 >= half 90 天内过期 → 排队报废；
  存放暗钟      温湿敏感剂型 × 浴室警告，热敏剂型 × 车内/阳台 exit 4；
  衰减推演      什么都不做，N 天后战备率掉到哪 —— 药箱不是仓库，是沙漏。

设计立场：
  开封效期默认表是常识先验不是药典，盒上说明永远赢（行内 open_days 覆盖）。
  账本是库存快照不是事件流 —— 缺省 as-of = 最近一次开封日，--as-of 钉死后
  同一本账任何机器逐字节一致；全账无开封记录时拒绝猜测。
  拒答优先 —— 盒数 < 5 不出统计判决（night 恒开庭，半夜不等样本）。
  不做医疗建议，永不提剂量；qty 是自报快照，不扫药箱。

零依赖：Python 3.8+ 纯标准库。MIT © 2026
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

EXIT_OK = 0
EXIT_BROKEN = 2      # 账本结构性损坏 / 参数错误
EXIT_DECLINE = 3     # 样本不足（THIN），拒绝统计判决
EXIT_REDLINE = 4     # 红线：场景裸奔 / 战备不及格 / 囤积报废 / 热敏存放

LOW_LINE_DEFAULT = 3     # 剩余使用单位 <= 此线判 LOW
READINESS_LINE = 0.50    # 战备率红线
THIN_MIN = 5             # 盒数下限，低于则拒判统计指标
HOARD_MIN = 3            # 同名 >= 3 盒点名
HOARD_WINDOW = 90        # 囤积报废观察窗（天）
HOARD_FRAC = 0.5         # 窗内将过期占比 >= half → 报废警报
SIM_WINDOW = 90          # hoard 默认观察窗（同上）

# 开封钟默认表（天）：剂型 → 开封后可用天数。None = 无开封钟（独立密封）。
# 常识先验，盒上说明永远赢。
OPEN_CLOCK = {
    "eyedrops": 28,      # 眼药水：防腐剂耗尽、黏膜接触，最严
    "syrup": 30,         # 糖浆/混悬液：微生物、分层
    "iodine": 30,        # 碘伏等消毒液：有效碘挥发
    "suppository": 30,   # 栓剂：基质软化析出
    "lozenge": 90,       # 含片/泡腾片：吸潮
    "spray": 90,         # 喷雾
    "bottle": 180,       # 瓶装片剂：每开一次盖换一次气
    "cream": 180,        # 软膏：破乳析水
    "other": 90,
    "blister": None,     # 铝箔/袋装单剂量密封：开封事件对整体不发生
}

# 半夜场景 → 弹药角色
SCENES = {
    "fever": "antipyretic",     # 发热/疼痛
    "gut": "antidiarrheal",     # 腹泻/脱水
    "wound": "disinfectant",    # 外伤/消毒
    "allergy": "antihistamine", # 过敏
}
SCENE_LABEL = {
    "fever": "发热疼痛", "gut": "腹泻脱水",
    "wound": "外伤消毒", "allergy": "抗过敏",
}
# 场景辅助弹药：参与披露、不参与判定（创可贴救不了没消毒的伤口）
SCENE_AUX = {"wound": ("dressing", "敷料")}
KIDS_ROLE_LABEL = "儿童剂型"

ROLE_LABEL = {
    "antipyretic": "退烧止痛", "antidiarrheal": "腹泻肠胃",
    "disinfectant": "外伤消毒", "antihistamine": "抗过敏",
    "dressing": "敷料辅助", "supplement": "补剂", "other": "其他",
}
FORM_LABEL = {
    "blister": "铝箔/袋装", "bottle": "瓶装片剂", "syrup": "糖浆/混悬",
    "eyedrops": "眼药水", "cream": "软膏", "iodine": "碘伏/消毒液",
    "suppository": "栓剂", "lozenge": "含片/泡腾", "spray": "喷雾",
    "other": "其他剂型",
}

# 存放审计：温湿敏感剂型 × 浴室；热敏剂型 × 高温位置
STASH_DAMP_FORMS = {"eyedrops", "syrup", "cream", "iodine",
                    "suppository", "lozenge", "spray", "bottle"}
STASH_HEAT_FORMS = {"suppository", "syrup"}   # 栓剂 35°C 软化、糖浆分层
BATH_KEYWORDS = ["浴室", "卫生间", "洗手间", "盥洗", "bathroom", "washroom"]
HEAT_KEYWORDS = ["车", "阳台", "窗台", "窗边", "暖气", "灶",
                 "car", "balcony", "windowsill", "sill", "heater", "stove"]

VERDICT_ORDER = {"EXPIRED": 0, "OPENED_OUT": 1, "LOW": 2, "READY": 3}
VERDICT_GLYPH = {"EXPIRED": "✗", "OPENED_OUT": "✗", "LOW": "◐", "READY": "✓"}
VERDICT_CN = {"EXPIRED": "包装钟已停", "OPENED_OUT": "开封钟已停",
              "LOW": "量见底", "READY": "在役"}

COLUMNS = ["name", "role", "form", "kids", "qty", "unit",
           "expiry", "opened", "location", "open_days", "note"]


class StructuralError(Exception):
    """账本结构性损坏（exit 2）。"""


# ---------------------------------------------------------------- 展示辅助

def disp_w(s: str) -> int:
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def pad(s: str, w: int) -> str:
    return s + " " * max(0, w - disp_w(s))


def fmt_date(d: Optional[date]) -> str:
    return d.isoformat() if d else "—"


def pct(n: int, total: int) -> str:
    return "—%" if total == 0 else f"{100.0 * n / total:.1f}%"


# ---------------------------------------------------------------- 账本模型

@dataclass
class Box:
    lineno: int
    name: str
    role: str
    form: str
    kids: bool
    qty: int
    unit: str
    expiry: date
    opened: Optional[date]
    location: str
    open_days: Optional[int]
    note: str

    def open_deadline(self) -> Optional[date]:
        """开封钟终点；未开封或剂型无开封钟 → None。"""
        days = self._clock_days()
        if self.opened is None or days is None:
            return None
        return self.opened + timedelta(days=days)

    def _clock_days(self) -> Optional[int]:
        if self.open_days is not None:
            return self.open_days          # 说明书永远赢
        return OPEN_CLOCK[self.form]

    def deadline(self) -> date:
        """两口钟取 min：任何一个先到终点，药就死了。"""
        od = self.open_deadline()
        if od is not None and od < self.expiry:
            return od
        return self.expiry

    def verdict(self, as_of: date, low_line: int = LOW_LINE_DEFAULT) -> str:
        if self.expiry < as_of:
            return "EXPIRED"
        od = self.open_deadline()
        if od is not None and od < as_of:
            return "OPENED_OUT"
        if self.qty <= low_line:
            return "LOW"
        return "READY"


def parse_date(s: str, ctx: str) -> date:
    try:
        return date(*(int(x) for x in s.split("-")))
    except Exception:
        raise StructuralError(f"第 {ctx} 行日期无法解析：{s!r}（要 YYYY-MM-DD）")


def load_ledger(path: str) -> List[Box]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter="\t"))
    except FileNotFoundError:
        raise StructuralError(f"账本不存在：{path}")
    except UnicodeDecodeError:
        raise StructuralError(f"账本不是 UTF-8：{path}")

    boxes: List[Box] = []
    header: Optional[List[str]] = None
    for i, raw in enumerate(rows, 1):
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        if cells[0].startswith("#"):
            continue
        if header is None:
            if cells[:1] != ["name"]:
                raise StructuralError(f"第 {i} 行应为表头（首列 name）：{cells[:3]}")
            header = cells
            if header[:len(COLUMNS)] != COLUMNS:
                raise StructuralError(
                    "表头不符：前 11 列应为 "
                    + "/".join(COLUMNS) + f"，实为 " + "/".join(header[:11]))
            continue
        if header is None or len(cells) < len(COLUMNS):
            raise StructuralError(f"第 {i} 行列数不足（{len(cells)} < {len(COLUMNS)}）")
        rec = dict(zip(COLUMNS, cells))
        ctx = str(i)

        name = rec["name"]
        if not name:
            raise StructuralError(f"第 {ctx} 行缺药名")
        if rec["role"] not in ROLE_LABEL:
            raise StructuralError(
                f"第 {ctx} 行未知角色 role={rec['role']!r}（{name}），"
                f"合法值：{'/'.join(ROLE_LABEL)}")
        if rec["form"] not in FORM_LABEL:
            raise StructuralError(
                f"第 {ctx} 行未知剂型 form={rec['form']!r}（{name}），"
                f"合法值：{'/'.join(FORM_LABEL)}")
        kids_raw = rec["kids"].lower()
        if kids_raw not in ("", "y", "n"):
            raise StructuralError(f"第 {ctx} 行 kids 只认 y/n/空：{rec['kids']!r}")
        try:
            qty = int(rec["qty"])
        except ValueError:
            raise StructuralError(f"第 {ctx} 行数量不是整数：{rec['qty']!r}（{name}）")
        if qty <= 0:
            raise StructuralError(f"第 {ctx} 行数量 <= 0（{name}）：用完的药请移出账本")
        expiry = parse_date(rec["expiry"], ctx)
        opened = parse_date(rec["opened"], ctx) if rec["opened"] else None
        open_days = None
        if rec["open_days"]:
            try:
                open_days = int(rec["open_days"])
            except ValueError:
                raise StructuralError(
                    f"第 {ctx} 行 open_days 不是整数：{rec['open_days']!r}（{name}）")
            if open_days <= 0:
                raise StructuralError(f"第 {ctx} 行 open_days 必须 > 0（{name}）")
        if opened is not None and opened > expiry:
            # 开封那天包装已过期：数据自相矛盾，validate 会披露，其余命令按 EXPIRED 走
            pass
        boxes.append(Box(
            lineno=i, name=name, role=rec["role"], form=rec["form"],
            kids=(kids_raw == "y"), qty=qty, unit=rec["unit"],
            expiry=expiry, opened=opened, location=rec["location"],
            open_days=open_days, note=rec["note"]))
    if header is None:
        raise StructuralError("账本为空：缺表头行")
    return boxes


def check_futures(boxes: List[Box], as_of: date) -> None:
    for b in boxes:
        if b.opened is not None and b.opened > as_of:
            raise StructuralError(
                f"第 {b.lineno} 行 {b.name}：开封日期 {b.opened} 晚于 as-of "
                f"{as_of} —— 未来开封的药不存在，查一下笔误")


def resolve_as_of(explicit: Optional[str], boxes: List[Box]) -> Tuple[date, str]:
    """快照账本的「今天」：显式 --as-of，或最近一次开封日（并披露）。"""
    if explicit:
        return parse_date(explicit, "--as-of"), "显式钉死"
    opened = [b.opened for b in boxes if b.opened is not None]
    if not opened:
        raise StructuralError(
            "快照账本没有事件流，全账无开封记录，缺省 as-of 无从谈起 —— "
            "请用 --as-of YYYY-MM-DD 显式钉死今天")
    return max(opened), "缺省=最近开封日"


# ---------------------------------------------------------------- 各命令

def cmd_report(boxes: List[Box], as_of: date, as_of_src: str,
               low_line: int) -> int:
    total = len(boxes)
    if total < THIN_MIN:
        print(f"THIN —— 药箱只有 {total} 盒，不构成「战备结构」，"
              f"统计判决拒绝下结论（逐盒点名 rollcall 仍可用）。exit 3")
        return EXIT_DECLINE

    counts = {v: 0 for v in VERDICT_ORDER}
    for b in boxes:
        counts[b.verdict(as_of, low_line)] += 1
    ready = counts["READY"]
    readiness = 1.0 * ready / total

    print("=" * 62)
    print("药箱点名 · Medicine Rollcall —— 战备总账")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）    LOW 线：qty <= {low_line}")
    print(f"盘点：{total} 盒")
    print()
    print("状态分布（判决互斥完备）：")
    for v in ("READY", "LOW", "OPENED_OUT", "EXPIRED"):
        print(f"  {VERDICT_GLYPH[v]} {pad(VERDICT_CN[v], 12)} "
              f"{pad(str(counts[v]) + ' 盒', 8)} {pct(counts[v], total)}")
    print(f"  恒等式：{counts['READY']} + {counts['LOW']} + "
          f"{counts['OPENED_OUT']} + {counts['EXPIRED']} = {total} ✓")
    print()
    print(f"战备率（真弹药占比）：{ready}/{total} = {pct(ready, total)}")
    if readiness < READINESS_LINE:
        print(f"  ✗ 低于 {int(READINESS_LINE * 100)}% 红线 —— 药箱的一半是安慰剂。")
    else:
        print(f"  ✓ 在 {int(READINESS_LINE * 100)}% 红线之上。")
    print()

    if counts["OPENED_OUT"]:
        print("开封钟阵亡名单（盒上没过期、药已死 —— 本工具存在的理由）：")
        dead = [b for b in boxes if b.verdict(as_of, low_line) == "OPENED_OUT"]
        dead.sort(key=lambda b: b.open_deadline())
        for b in dead:
            dl = b.open_deadline()
            days = (as_of - dl).days
            print(f"  ✗ {pad(b.name, 16)} 开封钟 {dl} 已停 {days} 天"
                  f"（包装钟到 {fmt_date(b.expiry)}，还活着）")
        print()

    if counts["EXPIRED"]:
        expired = [b for b in boxes if b.verdict(as_of, low_line) == "EXPIRED"]
        oldest = min(b.expiry for b in expired)
        print(f"包装钟阵亡：{counts['EXPIRED']} 盒，最早停在 {oldest}"
              f"（距今 {(as_of - oldest).days} 天——箱底考古现场）。")
        print()

    print("半夜场景速览（详单见 coverage / night）：")
    any_red = False
    for scene, role in SCENES.items():
        ammo = [b for b in boxes if b.role == role]
        usable = [b for b in ammo
                  if b.verdict(as_of, low_line) in ("READY", "LOW")]
        if not usable:
            mark, word = "✗", "BARE 裸奔"
            any_red = True
        elif all(b.verdict(as_of, low_line) == "LOW" for b in usable):
            mark, word = "◐", "AMMO-LOW 见底"
        else:
            mark, word = "✓", "OK"
        kids_ammo = [b for b in ammo if b.kids]
        kids_usable = [b for b in kids_ammo
                       if b.verdict(as_of, low_line) in ("READY", "LOW")]
        kids_word = ("（儿童栏 ✗）" if kids_ammo and not kids_usable else "")
        print(f"  {mark} {pad(SCENE_LABEL[scene], 10)} {pad(word, 14)}"
              f"{len(usable)}/{len(ammo)} 盒可用{kids_word}")
    print()

    print("诚实条款：qty 是自报快照，本工具不扫药箱——你亲手数一遍，")
    print("才是唯一的 verify；开封效期默认表是常识先验，盒上说明永远赢；")
    print("本工具不做医疗建议，红灯请带去药房或问医生。")
    rc = EXIT_REDLINE if (readiness < READINESS_LINE or any_red) else EXIT_OK
    if rc:
        why = []
        if readiness < READINESS_LINE:
            why.append("战备不及格")
        if any_red:
            why.append("场景裸奔")
        print(f"exit {rc}（{' + '.join(why)}）")
    else:
        print("exit 0")
    return rc


def cmd_rollcall(boxes: List[Box], as_of: date, as_of_src: str,
                 low_line: int) -> int:
    print("=" * 62)
    print("逐盒点名 —— 每一盒药对两口钟各自报数")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）    判决：EXPIRED>OPENED_OUT>LOW>READY")
    print()
    ordered = sorted(boxes, key=lambda b: (VERDICT_ORDER[b.verdict(as_of, low_line)],
                                           b.verdict(as_of, low_line), b.name, b.lineno))
    for b in ordered:
        v = b.verdict(as_of, low_line)
        dl = b.deadline()
        kids = "儿童" if b.kids else "    "
        head = (f"{VERDICT_GLYPH[v]} {pad(b.name, 18)} {pad(kids, 6)}"
                f"{pad(ROLE_LABEL[b.role], 10)} {pad(FORM_LABEL[b.form], 12)}"
                f"{b.qty}{b.unit}  截止 {fmt_date(dl)}")
        print(head)
        if v == "EXPIRED":
            print(f"    包装钟 {b.expiry} 已停 {(as_of - b.expiry).days} 天"
                  + ("——开封那天包装就已过期，账本自相矛盾"
                     if b.opened and b.opened > b.expiry else ""))
        elif v == "OPENED_OUT":
            od = b.open_deadline()
            print(f"    盒未过期（{fmt_date(b.expiry)}），开封钟 {od} 已停 "
                  f"{(as_of - od).days} 天 —— 药盒没过期，药死了")
        elif v == "LOW":
            od = b.open_deadline()
            tail = f"，开封钟到 {fmt_date(od)}" if od else ""
            print(f"    双钟都在期内{tail}，剩余 {b.qty}{b.unit} ≤ LOW 线 {low_line}"
                  " —— 半夜够不够用，自己掂量")
        else:
            od = b.open_deadline()
            if od and od <= as_of + timedelta(days=7):
                print(f"    在役，但开封钟 {od} 只剩 {(od - as_of).days} 天 —— "
                      "最近就要用完或换新")
        if b.note:
            print(f"    · {b.note}")
    print()
    print("点名不判罪：LOW 是黄牌不是死刑，扔与补仍是人的决定。")
    return EXIT_OK


def _night_scene(boxes: List[Box], scene: str, who: str,
                 as_of: date, low_line: int) -> Tuple[List[Box], List[Box], List[Box]]:
    role = SCENES[scene]
    ammo = [b for b in boxes if b.role == role]
    if who == "kid":
        ammo = [b for b in ammo if b.kids]
    usable = [b for b in ammo if b.verdict(as_of, low_line) in ("READY", "LOW")]
    dead = [b for b in ammo if b not in usable]
    return ammo, usable, dead


def cmd_night(boxes: List[Box], as_of: date, as_of_src: str, scene: str,
              who: str, low_line: int) -> int:
    if scene not in SCENES:
        print(f"未知场景 {scene!r}：可选 {'/'.join(SCENES)}")
        return EXIT_BROKEN
    print("=" * 62)
    print(f"半夜测试 · night {scene}（{SCENE_LABEL[scene]}）")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）    弹药角色：{SCENES[scene]}")
    if who == "kid":
        print("口径：--who kid —— 只认儿童剂型，成人片剂掰半不算数。")
    if len(boxes) < THIN_MIN:
        print(f"⚠ 样本薄（全账 {len(boxes)} 盒）：半夜不等样本，照常开庭。")
    print()

    ammo, usable, dead = _night_scene(boxes, scene, who, as_of, low_line)
    if not ammo:
        print(f"点名：该场景在账本里没有任何弹药记录（role={SCENES[scene]}）。")
        print()
        print("判决：BARE —— 半夜这个场景，药箱连弹药库都没有。")
        print("补什么药问药师；今晚这关，先想别的办法。")
        return EXIT_REDLINE

    print(f"弹药点名（{len(ammo)} 盒）：")
    for b in sorted(ammo, key=lambda b: (b.verdict(as_of, low_line) != "READY",
                                         b.name)):
        v = b.verdict(as_of, low_line)
        od = b.open_deadline()
        extra = ""
        if v == "OPENED_OUT":
            extra = f"包装钟到 {fmt_date(b.expiry)} 活着，开封钟 {od} 已停"
        elif v == "EXPIRED":
            extra = f"包装钟 {b.expiry} 已停 {(as_of - b.expiry).days} 天"
        elif v == "LOW":
            t = f"开封钟到 {fmt_date(od)}" if od else "双钟都在期内"
            extra = f"{t}，剩 {b.qty}{b.unit}"
        else:
            t = f"开封钟到 {fmt_date(od)}" if od else "双钟都在期内"
            extra = f"{t}，{b.qty}{b.unit}"
        print(f"  {VERDICT_GLYPH[v]} {pad(b.name, 18)} "
              f"{pad(VERDICT_CN[v], 12)} {extra}")
    aux = SCENE_AUX.get(scene)
    if aux and who != "kid":
        aux_role, aux_label = aux
        aux_boxes = [b for b in boxes if b.role == aux_role]
        if aux_boxes:
            aux_usable = [b for b in aux_boxes
                          if b.verdict(as_of, low_line) in ("READY", "LOW")]
            print(f"  ○ 辅助弹药（{aux_label}，不顶主力）："
                  + "、".join(f"{b.name} {b.qty}{b.unit}"
                              + ("✓" if b in aux_usable else "✗")
                              for b in aux_boxes))
    print()

    if not usable:
        print("判决：BARE —— 半夜这个场景，药箱接不住。exit 4")
        if dead:
            cause = "；".join(f"{b.name}（{'包装钟' if b.verdict(as_of, low_line) == 'EXPIRED' else '开封钟'}已停）"
                             for b in dead)
            print(f"阵亡详情：{cause}。")
            kids_live = [b for b in dead if b.kids]
            if who != "kid" and kids_live:
                print("盒上的效期是给未开封的药印的——开了封，另一口钟说了算。")
        else:
            print("药箱里根本没这个科目——囤的是感冒，半夜来的是这个。")
        print("红灯指向药师与医生：补什么、怎么补，问专业；今晚先用别的方式过。")
        return EXIT_REDLINE

    if all(b.verdict(as_of, low_line) == "LOW" for b in usable):
        print("判决：AMMO-LOW —— 接得住，但弹药见底。exit 0")
        print("今晚有答案，明天记得补货——见底的弹药撑不了第二次半夜。")
        return EXIT_OK

    print(f"判决：OK —— 弹药在架，{len(usable)}/{len(ammo)} 盒接得住。exit 0")
    kids_ammo = [b for b in ammo if b.kids]
    kids_usable = [b for b in kids_ammo
                   if b.verdict(as_of, low_line) in ("READY", "LOW")]
    if who != "kid" and kids_ammo and not kids_usable:
        print("⚠ 儿童栏：全灭 —— "
              + "；".join(f"{b.name}（{VERDICT_CN[b.verdict(as_of, low_line)]}）"
                         for b in kids_ammo))
        print("  孩子的药箱比大人的先阵亡：儿童药开封即弃、用不完即浪费，")
        print("  大人总舍不得补货。大人的 ✓ 管不了孩子的半夜。")
    return EXIT_OK


def cmd_coverage(boxes: List[Box], as_of: date, as_of_src: str,
                 low_line: int) -> int:
    total = len(boxes)
    if total < THIN_MIN:
        print(f"THIN —— 药箱只有 {total} 盒，不构成「战备结构」，"
              f"场景矩阵拒绝下结论。exit 3")
        return EXIT_DECLINE
    print("=" * 62)
    print("场景覆盖矩阵 —— 半夜真会来的四个场景，各自过闸")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）")
    print()
    any_red = False
    lines = []
    for scene, role in SCENES.items():
        ammo = [b for b in boxes if b.role == role]
        usable_ready = [b for b in ammo if b.verdict(as_of, low_line) == "READY"]
        usable = [b for b in ammo if b.verdict(as_of, low_line) in ("READY", "LOW")]
        kids_usable = [b for b in usable if b.kids]
        kids_ammo = [b for b in ammo if b.kids]
        if not usable:
            mark, word = "✗", "RED  BARE"
            any_red = True
            why = "无可用弹药" + ("（科目空白）" if not ammo else "（全部阵亡）")
        elif not usable_ready:
            mark, word = "◐", "YELLO AMMO-LOW"
            why = f"可用弹药全部见底（{len(usable)} 盒 ≤ LOW 线）"
        else:
            mark, word = "✓", "GREEN    "
            why = f"{len(usable_ready)} 盒真弹药在役"
        kids_word = ""
        if kids_ammo and not kids_usable:
            kids_word = "  ⚠ 儿童栏全灭"
        lines.append((scene, mark, word, len(usable), len(ammo), why, kids_word))
        # 场景弹药恒等式：可用 = READY + LOW，账面必须对得上
        assert len(usable) == len(usable_ready) + sum(
            1 for b in ammo if b.verdict(as_of, low_line) == "LOW")
    for scene, mark, word, n_use, n_ammo, why, kids_word in lines:
        print(f"{mark} {pad(SCENE_LABEL[scene], 10)} {word}   "
              f"{n_use}/{n_ammo} 盒可用   {why}{kids_word}")
    print()
    print("场景弹药恒等式：每场景可用数 = READY + LOW，逐场景对账精确。")
    print("创可贴是 dressing 不是 disinfectant——不消毒就封口，是把细菌打包。")
    if any_red:
        print("有场景裸奔：今晚它不来则已，来一次就是一次措手不及。exit 4")
        return EXIT_REDLINE
    print("四场景全有接应。exit 0")
    return EXIT_OK


def cmd_hoard(boxes: List[Box], as_of: date, as_of_src: str,
              window: int) -> int:
    print("=" * 62)
    print(f"囤积质证 —— 同名 >= {HOARD_MIN} 盒点名，与效期交叉对质")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）    报废观察窗：{window} 天")
    print()
    by_name: Dict[str, List[Box]] = {}
    for b in boxes:
        by_name.setdefault(b.name, []).append(b)
    groups = [(n, bs) for n, bs in by_name.items() if len(bs) >= HOARD_MIN]
    groups.sort(key=lambda x: (-len(x[1]), x[0]))
    if not groups:
        print(f"没有同名 >= {HOARD_MIN} 盒的科目，无囤积可质证。exit 0")
        return EXIT_OK
    rc = EXIT_OK
    for name, bs in groups:
        alive = [b for b in bs if b.expiry >= as_of]
        already = len(bs) - len(alive)
        end = as_of + timedelta(days=window)
        expiring = [b for b in alive if b.deadline() <= end]
        frac = (1.0 * len(expiring) / len(alive)) if alive else 1.0
        flag = "✗ 报废流水线" if alive and frac >= HOARD_FRAC else "◐ 囤积点名"
        if alive and frac >= HOARD_FRAC:
            rc = EXIT_REDLINE
        print(f"{flag}  {name} × {len(bs)} 盒")
        for b in sorted(bs, key=lambda b: b.expiry):
            v = b.verdict(as_of)
            dl = b.deadline()
            tail = "（已过期）" if v == "EXPIRED" else (
                f"→ {dl} 过期（{window} 天窗内）"
                if v != "EXPIRED" and dl <= end else f"→ {dl} 过期")
            print(f"    {VERDICT_GLYPH[v]} 剩 {b.qty}{b.unit}，包装钟 {b.expiry} {tail}")
        if alive and frac >= HOARD_FRAC:
            print(f"    ✗ 未过期 {len(alive)} 盒里 {len(expiring)} 盒在 {window} 天内到期"
                  f"（{int(frac * 100)}% >= {int(HOARD_FRAC * 100)}% 线）——")
            print("      这不是储备，是一条排队的报废流水线：为感冒囤的药，")
            print("      感冒没来，效期先来。到期的盒子里装的是提前付过钱的垃圾桶。")
        elif alive:
            print(f"    ◐ 未过期 {len(alive)} 盒里 {len(expiring)} 盒 {window} 天内到期"
                  f"——还没过半，下次囤货前先数数这一格。")
        if already:
            print(f"    · 另有 {already} 盒已过期，正在箱底装死。")
        print()
    print("囤积本身不是罪——急救储备是合理的。要质证的是囤积 × 效期的交集。")
    print(f"exit {rc}" + ("（报废流水线亮灯）" if rc else ""))
    return rc


def _loc_hits(location: str) -> Tuple[bool, bool]:
    low = location.lower()
    bath = any(k.lower() in low for k in BATH_KEYWORDS)
    heat = any(k.lower() in low for k in HEAT_KEYWORDS)
    return bath, heat


def cmd_stash(boxes: List[Box]) -> int:
    print("=" * 62)
    print("存放审计 —— 效期承诺以「规定储存条件」为前提")
    print("=" * 62)
    print("关键词只认你写进 location 的字，工具不猜：浴室=温湿，")
    print("车内/阳台/窗台/暖气=高温。密封 blister 对浴室免疫。")
    print()
    rc = EXIT_OK
    hits = 0
    for b in boxes:
        bath, heat = _loc_hits(b.location)
        if bath and b.form in STASH_DAMP_FORMS:
            hits += 1
            print(f"⚠ {pad(b.name, 18)} {pad(FORM_LABEL[b.form], 12)}"
                  f"在「{b.location}」—— 温湿敏感剂型怕浴室的昼夜蒸腾")
            if b.form in STASH_HEAT_FORMS:
                print(f"   {FORM_LABEL[b.form]}同时是热敏剂型：浴室夏天常年超标，"
                      f"挪去阴凉干燥处")
        elif bath:
            print(f"· {pad(b.name, 18)} {pad(FORM_LABEL[b.form], 12)}"
                  f"在浴室——密封包装，免疫，随它")
        if heat and b.form in STASH_HEAT_FORMS:
            hits += 1
            rc = EXIT_REDLINE
            print(f"✗ {pad(b.name, 18)} {pad(FORM_LABEL[b.form], 12)}"
                  f"在「{b.location}」—— 栓剂 35°C 软化、糖浆受热分层，")
            print(f"   这格位置的夏天比 {FORM_LABEL[b.form]} 的熔点热。exit 4")
        elif heat:
            hits += 1
            print(f"⚠ {pad(b.name, 18)} {pad(FORM_LABEL[b.form], 12)}"
                  f"在「{b.location}」—— 高温位置，剂型不热敏但也不占便宜")
    if not hits:
        print("存放审计安静通过：没有敏感剂型住在错误的位置。exit 0")
        return EXIT_OK
    print()
    print("存放是第三口暗钟：位置写错的药，效期是按错误前提承诺的。")
    print(f"exit {rc}" + ("（热敏剂型住进高温位置）" if rc else "（温湿警告，建议挪窝）"))
    return rc


def cmd_simulate(boxes: List[Box], as_of: date, as_of_src: str,
                 days: int, low_line: int) -> int:
    total = len(boxes)
    if total < THIN_MIN:
        print(f"THIN —— 药箱只有 {total} 盒，衰减推演拒绝下结论。exit 3")
        return EXIT_DECLINE

    def ready_at(day: int) -> int:
        d = as_of + timedelta(days=day)
        return sum(1 for b in boxes if b.verdict(d, low_line) == "READY")

    print("=" * 62)
    print(f"衰减推演 —— 什么都不做，{days} 天后药箱剩多少真弹药")
    print("=" * 62)
    print(f"as-of：{as_of}（{as_of_src}）    口径：战备率 = READY / 总盒数")
    print()
    day0 = ready_at(0)
    print(f"恒等式：day 0 战备率 {day0}/{total} = {pct(day0, total)}"
          "  == report 同一把尺子 ✓")
    points = sorted({0, days // 3, 2 * days // 3, days})
    print()
    print("战备率曲线（单调不增——药箱不会自己变好）：")
    prev = None
    mono = True
    for p in points:
        r = ready_at(p)
        if prev is not None and r > prev:
            mono = False
        prev = r
        d = as_of + timedelta(days=p)
        bar = "#" * r + "." * (total - r)
        print(f"  day {pad(str(p), 4)} {d}  [{bar}]  {r}/{total} = {pct(r, total)}")
    assert mono, "战备率曲线必须单调不增"
    print()
    print("翻牌日历（每一盒 min 钟的终点，精确到天）：")
    end = as_of + timedelta(days=days)
    events = []
    for b in boxes:
        if b.verdict(as_of, low_line) == "EXPIRED":
            continue
        dl = b.deadline()
        flip = dl + timedelta(days=1)
        if as_of <= flip <= end:
            events.append((flip, b))
    events.sort(key=lambda e: (e[0], e[1].name, e[1].lineno))
    if not events:
        print("  观察窗内无翻牌——这个药箱的反面教材。")
    for flip, b in events:
        print(f"  {flip}  {pad(b.name, 18)} "
              f"{('包装钟到 ' + fmt_date(b.expiry)) if b.deadline() == b.expiry else ('开封钟到 ' + fmt_date(b.deadline()))}"
              f" → 阵亡")
    final = ready_at(days)
    print()
    print(f"结论：day {days} 战备率 {pct(final, total)}"
          + f"（day 0 为 {pct(day0, total)}）"
          if days > 0 else f"结论：day 0 战备率 {pct(final, total)}")
    if final < day0:
        print("药箱不是仓库，是沙漏——「以后再收拾」的每一天都有单价。")
    print("推演永不替你动药箱：清点、补货、处置，仍是人的决定。exit 0")
    return EXIT_OK


def cmd_validate(boxes: List[Box], as_of: Optional[date]) -> int:
    print("=" * 62)
    print("账本体检 —— 结构已过解析层（坏列/坏日期/坏数量在此前已 exit 2）")
    print("=" * 62)
    print()
    rc = EXIT_OK
    warns = 0
    if as_of is not None:
        for b in boxes:
            if b.opened is not None and b.opened > as_of:
                print(f"✗ 第 {b.lineno} 行 {b.name}：开封 {b.opened} 晚于 as-of "
                      f"{as_of} —— 未来开封的药不存在。exit 2")
                rc = EXIT_BROKEN
    for b in boxes:
        if b.opened is not None and b.opened > b.expiry:
            warns += 1
            print(f"⚠ 第 {b.lineno} 行 {b.name}：开封 {b.opened} 晚于包装效期 "
                  f"{b.expiry} —— 开封那天药已过期，查笔误或直接处置")
    seen: Dict[Tuple[str, str], int] = {}
    for b in boxes:
        key = (b.name, b.expiry.isoformat())
        seen[key] = seen.get(key, 0) + 1
    for (name, exp), n in sorted(seen.items()):
        if n > 1:
            warns += 1
            print(f"⚠ {name} @ {exp} 出现 {n} 行 —— 同名同效期疑似重复录入，"
                  "囤货请合并数量或用 note 区分")
    if not any(b.opened for b in boxes):
        print("· 全账无开封记录：开封钟从未启动，统计口径等于包装钟。")
    if warns == 0 and rc == EXIT_OK:
        print("账本干净：无矛盾、无重复、无未来开封。exit 0")
    else:
        print(f"exit {rc}")
    return rc


# ---------------------------------------------------------------- 参数装配

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="medicine_rollcall.py",
        description="药箱点名 · Medicine Rollcall —— 家庭药箱战备审计（零依赖）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, need_days=False):
        sp.add_argument("ledger", help="药箱库存快照 TSV")
        sp.add_argument("--as-of", dest="as_of", default=None,
                        help="钉死今天 YYYY-MM-DD（缺省=最近开封日）")
        sp.add_argument("--low-line", type=int, default=LOW_LINE_DEFAULT,
                        help=f"LOW 判决线（默认 qty <= {LOW_LINE_DEFAULT}）")

    for name, help_ in [
            ("report", "战备总账：状态分布/战备率/双钟归因/场景速览"),
            ("rollcall", "逐盒点名：两口钟各自报数，死因归到钟"),
            ("coverage", "四场景覆盖矩阵，任一 RED exit 4"),
            ("hoard", "囤积质证：同名 >=3 盒 × 效期交叉"),
            ("validate", "账本体检：矛盾/重复/未来开封")]:
        sp = sub.add_parser(name, help=help_)
        common(sp)
    sp = sub.add_parser("night", help="半夜测试：单场景开庭，BARE exit 4")
    common(sp)
    sp.add_argument("--scene", required=True,
                    choices=sorted(SCENES), help="半夜场景")
    sp.add_argument("--who", choices=["all", "kid"], default="all",
                    help="kid=只认儿童剂型")
    sp = sub.add_parser("stash", help="存放审计：位置关键词 × 剂型敏感度")
    sp.add_argument("ledger", help="药箱库存快照 TSV")
    sp = sub.add_parser("simulate", help="衰减推演")
    common(sp)
    sp.add_argument("--days", type=int, default=SIM_WINDOW,
                    help=f"推演天数（默认 {SIM_WINDOW}）")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        boxes = load_ledger(args.ledger)
        if args.cmd == "stash":
            return cmd_stash(boxes)
        as_of, src = resolve_as_of(getattr(args, "as_of", None), boxes)
        check_futures(boxes, as_of)
        if args.cmd == "report":
            return cmd_report(boxes, as_of, src, args.low_line)
        if args.cmd == "rollcall":
            return cmd_rollcall(boxes, as_of, src, args.low_line)
        if args.cmd == "night":
            return cmd_night(boxes, as_of, src, args.scene, args.who,
                             args.low_line)
        if args.cmd == "coverage":
            return cmd_coverage(boxes, as_of, src, args.low_line)
        if args.cmd == "hoard":
            return cmd_hoard(boxes, as_of, src, HOARD_WINDOW)
        if args.cmd == "simulate":
            if args.days < 0:
                print("--days 不能为负")
                return EXIT_BROKEN
            return cmd_simulate(boxes, as_of, src, args.days, args.low_line)
        if args.cmd == "validate":
            return cmd_validate(boxes, as_of)
        print("未知命令")
        return EXIT_BROKEN
    except StructuralError as e:
        print(f"✗ 账本损坏：{e}")
        print("exit 2")
        return EXIT_BROKEN


if __name__ == "__main__":
    sys.exit(main())
