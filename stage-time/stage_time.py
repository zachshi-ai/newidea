#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""讲台时刻 · Stage Time — 讲稿的时长预算与超时预警。

零依赖（Python 3.8+ 标准库）。把「这份稿子念完到底要几分钟」的回答
从台上提前到写稿时：

  · 口播单位模型：汉字 1 单位/字、数字串逐位、英文词 1.8 单位，
    代码逐字符另计——语速不是常数，时长估算必须类型感知；
  · 结构停顿：翻页、段落、列表项、引用、代码演示各有固定成本；
  · 超时不均匀压缩：按牺牲优先级给出删除清单，核心论证受保护；
  · 核心观点位置：主张句出现太晚（>50%）亮红灯——埋伏笔是失败模式；
  · 个人语速校准：一次真实计时，反推口播单位速率并复用。

子命令：
  estimate   时长估算 + 预算判定
  cuts       超时时的按牺牲优先级压缩清单
  thesis     核心主张句的位置审计
  calibrate  用真实时长校准个人语速
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

# ---------------------------------------------------------------- 模型参数
DEFAULT_UNITS_PER_SECOND = 4.0   # 240 口播单位/分钟 ≈ 中文自然演讲语速
ENGLISH_WORD_UNITS = 1.8         # 一个英文词 ≈ 1.8 口播单位（240/133 wpm）
CODE_SECONDS_PER_CHAR = 0.12     # 念代码是逐字符的，远慢于叙述
HEADING_PAUSE = 1.5              # 标题后：翻页、停顿、等反应
PARAGRAPH_PAUSE = 0.6            # 段落之间
LIST_ITEM_PAUSE = 0.4            # 列表项之间
QUOTE_PAUSE = 0.8                # 引用块：放慢、换语气
CODE_BLOCK_PAUSE = 2.0           # 切到代码演示的固定成本
CONFIDENCE_BAND = 0.15           # ±15% 语速个体差异 → 时长区间
SAFETY_MARGIN = 1.05             # 压缩清单要多省 5%，防止临场反弹
MIN_CUT_SECONDS = 5.0            # 省 5 秒以下的块不值得出现在清单里

DEFAULT_PROFILE = os.path.join(os.path.expanduser("~"), ".stage-time.json")

# 核心主张句的信号词：第一处强命中即视为 thesis
THESIS_PATTERNS = [
    r"我认为", r"我主张", r"我想说的是", r"我今天想讲", r"核心观点是",
    r"关键在于", r"本文提出", r"我们提出", r"我的论点是", r"结论是",
    r"i argue", r"i propose", r"we propose", r"my claim",
    r"the key idea", r"the point (?:i want to make|of this talk) is",
]

# 牺牲优先级：数字越小越先删。未命中任何规则的块是核心内容，受保护。
SACRIFICE_RULES = [
    (0, "客套与元话语",
     r"(?i)(感谢|谢谢大家|百忙之中|深感荣幸|不吝赐教|废话不多说|不用我多说|"
     r"大家都知道|接下来我将|如我刚才所说|正如前面提到|thank you for|"
     r"as i mentioned|without further ado|in this talk,? i will)",
     "对内容零贡献的礼节与路标"),
    (1, "冗长背景",
     r"(?i)(很久以前|在过去|传统上|发展历程|历史沿革|前世今生|背景介绍|"
     r"由来已久|in the past|traditionally|a brief history|some background)",
     "听众默认已知、或可以留到 Q&A 的历史铺垫"),
    (2, "次要细节",
     r"(?i)(具体来说|举例来说|举个例子|细枝末节|展开讲讲|细节如下|"
     r"for example|for instance|in detail|to be more specific)",
     "论证的支撑层：砍掉不伤主张，只是少了插图"),
]
PROTECTED = (9, "核心内容")

# ---------------------------------------------------------------- 文本度量
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
DIGIT_RUN_RE = re.compile(r"[0-9]+")
EN_WORD_RE = re.compile(r"[A-Za-z]+")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
EMPHASIS_RE = re.compile(r"[*_]{1,3}([^*_]+)[*_]{1,3}")
THESIS_RE = re.compile("|".join(THESIS_PATTERNS), re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；.!?;])\s*")


def strip_inline(text):
    """去掉 markdown 行内标记（加粗/斜体），保留内容。"""
    return EMPHASIS_RE.sub(r"\1", text).strip()


def text_units(text):
    """叙述文本的口播单位：汉字 1/字、数字串逐位 1/位、英文词 1.8/词。

    行内代码不计入（它按字符秒数单独计，属于固定成本）。
    标点不计——停顿由结构模型统一处理，避免双重计算。
    """
    text = INLINE_CODE_RE.sub(" ", text)
    units = len(CJK_RE.findall(text))
    for run in DIGIT_RUN_RE.findall(text):
        units += len(run)  # 逐位念：2024 → 二-零-二-四
    units += ENGLISH_WORD_UNITS * len(EN_WORD_RE.findall(text))
    return units


def inline_code_seconds(text):
    total = 0.0
    for m in INLINE_CODE_RE.finditer(text):
        total += len(re.sub(r"\s+", "", m.group(1))) * CODE_SECONDS_PER_CHAR
    return total


# ---------------------------------------------------------------- 讲稿解析
def parse_blocks(markdown_text):
    """把 markdown 讲稿切成块序列 [(kind, text, line), ...]。

    kind ∈ {heading, paragraph, list_item, quote, code}。
    line 为 1 起始的行号，供压缩清单定位。
    """
    blocks = []
    lines = markdown_text.splitlines()
    para, para_line = [], 0
    i, n = 0, len(lines)

    def flush_paragraph():
        nonlocal para
        if para:
            blocks.append(("paragraph", " ".join(para).strip(), para_line))
            para = []

    while i < n:
        line = lines[i].strip()
        if line.startswith("```"):
            flush_paragraph()
            body, j = [], i + 1
            while j < n and not lines[j].strip().startswith("```"):
                body.append(lines[j])
                j += 1
            blocks.append(("code", "\n".join(body), i + 1))
            i = j + 1
            continue
        if not line:
            flush_paragraph()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_paragraph()
            blocks.append(("heading", strip_inline(m.group(2)), i + 1))
            i += 1
            continue
        if line.startswith(">"):
            flush_paragraph()
            blocks.append(("quote", strip_inline(re.sub(r"^>\s?", "", line)), i + 1))
            i += 1
            continue
        m = re.match(r"^[-*+]\s+(.*)$", line) or re.match(r"^\d+[.)]\s+(.*)$", line)
        if m:
            flush_paragraph()
            blocks.append(("list_item", strip_inline(m.group(1)), i + 1))
            i += 1
            continue
        if not para:
            para_line = i + 1
        para.append(strip_inline(line))
        i += 1
    flush_paragraph()
    return blocks


def block_seconds(kind, text, ups):
    """单块时长 → (text_seconds, fixed_seconds)。

    text_seconds 随个人语速（ups）缩放；fixed_seconds 是物理性的慢
    （念代码、停顿），不随语速缩放——校准时二者必须分开。
    """
    if kind == "code":
        chars = len(re.sub(r"\s+", "", text))
        return 0.0, chars * CODE_SECONDS_PER_CHAR + CODE_BLOCK_PAUSE
    fixed = inline_code_seconds(text)
    if kind == "heading":
        fixed += HEADING_PAUSE
    elif kind == "quote":
        fixed += QUOTE_PAUSE
    return text_units(text) / ups, fixed


def _segments(blocks, ups):
    """逐块产出 (kind, text, line, text_secs, fixed_secs)。

    块间停顿规则：标题自带翻页停顿（不再另加）；连续列表项之间用
    LIST_ITEM_PAUSE；其余相邻块之间用 PARAGRAPH_PAUSE。停顿计入
    fixed_secs——它不随个人语速缩放，校准时必须与叙述时间分开。
    """
    prev_kind = None
    for kind, text, line in blocks:
        text_secs, fixed = block_seconds(kind, text, ups)
        if prev_kind is not None:
            if kind == "heading":
                pass  # 标题已自带翻页停顿
            elif kind == "list_item" and prev_kind == "list_item":
                fixed += LIST_ITEM_PAUSE
            else:
                fixed += PARAGRAPH_PAUSE
        yield kind, text, line, text_secs, fixed
        prev_kind = kind


def timeline(blocks, ups):
    """全稿时间轴 → (total_seconds, per_block)。

    per_block 每项含 kind/text/line/seconds（含该块应分摊的结构停顿）。
    """
    per, total = [], 0.0
    for kind, text, line, text_secs, fixed in _segments(blocks, ups):
        per.append({"kind": kind, "text": text, "line": line,
                    "seconds": text_secs + fixed})
        total += text_secs + fixed
    return total, per


def split_sentences(text):
    return [s for s in SENTENCE_SPLIT_RE.split(text) if s and s.strip()]


def find_thesis(blocks, ups):
    """定位第一处核心主张句 → (sentence, position_pct, elapsed_seconds)。

    位置 = 该句开始时刻 / 全程时长。句内时长按块内口播单位占比分摊。
    """
    total, per = timeline(blocks, ups)
    elapsed = 0.0
    for item in per:
        unit_total = text_units(item["text"]) or 1.0
        block_secs = item["seconds"]
        cursor = 0.0  # 块内已消费的口播单位
        for sent in split_sentences(item["text"]):
            if THESIS_RE.search(sent):
                pct = elapsed / total if total > 0 else 0.0
                return sent.strip(), pct, elapsed
            cursor += text_units(sent)
            elapsed += block_secs * (text_units(sent) / unit_total)
    return None


# ---------------------------------------------------------------- 压缩清单
def classify_sacrifice(text):
    for priority, name, pattern, hint in SACRIFICE_RULES:
        if re.search(pattern, text):
            return priority, name, hint
    return PROTECTED[0], PROTECTED[1], "受保护：压缩清单永不建议删除主张与论证"


def build_cuts(blocks, ups, budget_seconds):
    """超时 → 按牺牲优先级排序的删除建议，累计节省 ≥ 超时×SAFETY_MARGIN。"""
    total, per = timeline(blocks, ups)
    overrun = total - budget_seconds
    need = overrun * SAFETY_MARGIN
    candidates = []
    protected = 0
    for item in per:
        priority, name, hint = classify_sacrifice(item["text"])
        if priority == PROTECTED[0]:
            protected += 1
        elif item["seconds"] >= MIN_CUT_SECONDS:
            candidates.append(dict(item, priority=priority, klass=name, hint=hint))
    candidates.sort(key=lambda c: (c["priority"], -c["seconds"]))
    suggestions, covered, cumulative = [], False, 0.0
    for cand in candidates:
        cumulative += cand["seconds"]
        suggestions.append(dict(cand, cumulative=cumulative))
        if cumulative >= need:
            covered = True
            break
    return {
        "total_seconds": total,
        "budget_seconds": budget_seconds,
        "overrun_seconds": overrun,
        "need_seconds": need,
        "suggestions": suggestions,
        "covered": covered,
        "protected_blocks": protected,
        "sacrifice_pool_seconds": sum(c["seconds"] for c in candidates),
    }


# ---------------------------------------------------------------- 语速档案
def load_profile(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_ups(profile, override):
    if override:
        return float(override)
    if profile.get("units_per_second"):
        return float(profile["units_per_second"])
    return DEFAULT_UNITS_PER_SECOND


def calibrate_ups(blocks, actual_seconds):
    """真实时长 → 个人口播速率。只反推叙述部分；固定成本（停顿+代码）
    不随语速缩放，必须先剔除——块间停顿与 timeline 同一套归账。
    """
    units_total, fixed_total = 0.0, 0.0
    for _, _, _, text_secs, fixed in _segments(blocks, DEFAULT_UNITS_PER_SECOND):
        units_total += text_secs * DEFAULT_UNITS_PER_SECOND  # 还原成口播单位数
        fixed_total += fixed
    if actual_seconds <= fixed_total:
        raise ValueError(
            "实际时长 %.1f 秒还不足以覆盖固定成本 %.1f 秒（停顿+代码），"
            "请确认计时与稿件一致" % (actual_seconds, fixed_total)
        )
    return units_total / (actual_seconds - fixed_total)


# ---------------------------------------------------------------- 命令实现
def fmt_minutes(seconds):
    return "%.1f 分钟" % (seconds / 60.0)


def fmt_seconds(seconds):
    return "%d 秒" % round(seconds)


def fmt_thousand(number):
    return "{:,}".format(round(number))


def estimate_data(path, ups, budget_seconds):
    with open(path, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())
    total, per = timeline(blocks, ups)
    units_total = sum(text_units(b[1]) for b in blocks)
    return {
        "file": path,
        "units": units_total,
        "blocks": len(blocks),
        "total_seconds": total,
        "minutes": total / 60.0,
        "band": (total * (1 - CONFIDENCE_BAND), total * (1 + CONFIDENCE_BAND)),
        "budget_seconds": budget_seconds,
        "overrun_seconds": total - budget_seconds,
        "verdict": "over" if total > budget_seconds else "within",
        "per_block": per,
    }


def cmd_estimate(args):
    ups = resolve_ups(load_profile(args.profile), args.rate)
    data = estimate_data(args.file, ups, args.budget * 60.0)
    if args.json:
        payload = {k: v for k, v in data.items() if k != "per_block"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    band_low, band_high = data["band"]
    print("讲台时刻 · Stage Time — 时长估算")
    print("  讲稿     : %s" % data["file"])
    print("  口播单位 : %s（%d 块）" % (fmt_thousand(data["units"]), data["blocks"]))
    print("  预计时长 : %s（乐观 %s / 悲观 %s）"
          % (fmt_minutes(data["total_seconds"]),
             fmt_minutes(band_low), fmt_minutes(band_high)))
    print("  时间预算 : %s" % fmt_minutes(data["budget_seconds"]))
    if data["verdict"] == "over":
        print("  判定     : ⚠️  超时 +%s —— 运行 cuts 获取按牺牲优先级排序的压缩清单"
              % fmt_minutes(data["overrun_seconds"]))
    else:
        print("  判定     : ✅ 预算内，余量 %s（建议留作 Q&A 缓冲）"
              % fmt_minutes(-data["overrun_seconds"]))
    return 0


def preview(text, width=28):
    one = re.sub(r"\s+", " ", text)
    return one if len(one) <= width else one[:width] + "……"


def cmd_cuts(args):
    ups = resolve_ups(load_profile(args.profile), args.rate)
    with open(args.file, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())
    result = build_cuts(blocks, ups, args.budget * 60.0)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if result["overrun_seconds"] <= 0:
        print("讲台时刻 · Stage Time — 压缩清单")
        print("  未超时（预算 %s），无需压缩。"
              % fmt_minutes(result["budget_seconds"]))
        return 0
    print("讲台时刻 · Stage Time — 压缩清单")
    print("  超时     : +%s，需要省 %s（含 %d%% 安全边际）"
          % (fmt_minutes(result["overrun_seconds"]),
             fmt_seconds(result["need_seconds"]),
             round((SAFETY_MARGIN - 1) * 100)))
    print("  可牺牲池 : %s（客套/背景/细节），核心内容 %d 块受保护"
          % (fmt_seconds(result["sacrifice_pool_seconds"]),
             result["protected_blocks"]))
    print()
    print("  按牺牲优先级（先删不痛的）：")
    for idx, sug in enumerate(result["suggestions"], 1):
        mark = " ✅ 已覆盖需求" if sug["cumulative"] >= result["need_seconds"] else ""
        print("   #%d [P%d %s] 第 %d 行起 省 %s | 累计 %s%s"
              % (idx, sug["priority"], sug["klass"], sug["line"],
                 fmt_seconds(sug["seconds"]),
                 fmt_seconds(sug["cumulative"]), mark))
        print("       “%s” —— %s" % (preview(sug["text"]), sug["hint"]))
    print()
    if result["covered"]:
        print("  结论：删以上 #%d 即可回到预算内，核心论证一字不动。"
              % len(result["suggestions"]))
    else:
        print("  结论：删光客套与背景也只省 %s < 需求 %s —— 不是删字的问题，"
              "需要动结构（合并章节或砍掉一个完整论点）。"
              % (fmt_seconds(result["sacrifice_pool_seconds"]),
                 fmt_seconds(result["need_seconds"])))
    return 0


def cmd_thesis(args):
    ups = resolve_ups(load_profile(args.profile), args.rate)
    with open(args.file, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())
    found = find_thesis(blocks, ups)
    total, _ = timeline(blocks, ups)
    if args.json:
        payload = {"file": args.file, "total_seconds": total}
        if found:
            sentence, pct, elapsed = found
            payload.update({"found": True, "sentence": sentence,
                            "position_pct": round(pct * 100),
                            "elapsed_seconds": elapsed})
        else:
            payload.update({"found": False})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("讲台时刻 · Stage Time — 核心观点位置")
    if not found:
        print("  检出     : （未检出主张句信号词）")
        print("  判定     : ⚪ 未检出——不硬猜；请确认稿中有一句"
              "“我认为/关键在于/I argue”式的主张")
        return 0
    sentence, pct, elapsed = found
    pct_int = round(pct * 100)
    if pct <= 0.25:
        judge, symbol = "前置到位（倒金字塔）", "🟢"
    elif pct <= 0.50:
        judge, symbol = "尚可，还能更前", "🟡"
    else:
        judge, symbol = "太晚——听众注意力峰值在前 25%，主张应前置", "🔴"
    print("  检出     : 「%s」" % preview(sentence, 40))
    print("  出现位置 : %d%%（第 %s / 全程 %s）"
          % (pct_int, fmt_minutes(elapsed), fmt_minutes(total)))
    print("  判定     : %s %s" % (symbol, judge))
    return 0


def cmd_calibrate(args):
    with open(args.file, encoding="utf-8") as f:
        blocks = parse_blocks(f.read())
    try:
        ups = calibrate_ups(blocks, args.actual * 60.0)
    except ValueError as exc:
        print("校准失败：%s" % exc, file=sys.stderr)
        return 2
    profile = {
        "units_per_second": round(ups, 4),
        "source": os.path.basename(args.file),
        "actual_minutes": args.actual,
        "calibrated_at": datetime.date.today().isoformat(),
    }
    if args.save:
        target = args.profile or DEFAULT_PROFILE
        with open(target, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        print("已写入 %s" % target)
    print("个人口播速率 : %.2f 单位/秒（默认 %.2f，%s%d%%）"
          % (ups, DEFAULT_UNITS_PER_SECOND,
             "慢" if ups < DEFAULT_UNITS_PER_SECOND else "快",
             round(abs(ups / DEFAULT_UNITS_PER_SECOND - 1) * 100)))
    print("下次 estimate/cuts/thesis 将自动使用（--profile 可指定档案）")
    return 0


# ---------------------------------------------------------------- CLI
def build_parser():
    parser = argparse.ArgumentParser(
        prog="stage_time",
        description="讲台时刻 · Stage Time — 讲稿的时长预算与超时预警（零依赖）")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("file", help="讲稿 markdown 路径")
        p.add_argument("--rate", type=float, default=None,
                       help="口播单位/秒，覆盖档案与默认值（默认 %.1f）"
                            % DEFAULT_UNITS_PER_SECOND)
        p.add_argument("--profile", default=None,
                       help="语速档案 JSON 路径（默认 ~/.stage-time.json）")
        p.add_argument("--json", action="store_true", help="机读输出")

    p_est = sub.add_parser("estimate", help="时长估算 + 预算判定")
    common(p_est)
    p_est.add_argument("--budget", type=float, required=True,
                       help="时间预算（分钟）")
    p_est.set_defaults(func=cmd_estimate)

    p_cuts = sub.add_parser("cuts", help="超时时的按牺牲优先级压缩清单")
    common(p_cuts)
    p_cuts.add_argument("--budget", type=float, required=True,
                        help="时间预算（分钟）")
    p_cuts.set_defaults(func=cmd_cuts)

    p_thesis = sub.add_parser("thesis", help="核心主张句的位置审计")
    common(p_thesis)
    p_thesis.set_defaults(func=cmd_thesis)

    p_cal = sub.add_parser("calibrate", help="用真实时长校准个人语速")
    common(p_cal)
    p_cal.add_argument("--actual", type=float, required=True,
                       help="真实讲完所用分钟数")
    p_cal.add_argument("--save", action="store_true",
                       help="写入语速档案")
    p_cal.set_defaults(func=cmd_calibrate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not os.path.exists(args.file):
        print("讲稿不存在：%s" % args.file, file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
