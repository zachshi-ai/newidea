#!/usr/bin/env python3
"""兜底 · Safety Floor.

A family coverage-gap ledger. Insurance is the only thing you buy hoping
never to use — and the only thing where "we have policies" and "we are
covered" are two different sentences. Agents sell by commission, not by
gap, so most households' portfolio is a sediment of sales history: the
pillar with zero life cover, the kid over-insured with savings-type
annuities that buy no protection at all.

safety-floor spreads every policy into one matrix of member x peril,
computes the target amount per cell from common-knowledge formulas
(life = income x 10, CI = expense x 3, medical = a million-yuan floor,
accident = max(income x 5, 200k) — the planner always wins, every
parameter is overridable), and grades each cell BARE / THIN / SHORT /
COVERED. The premium ledger adds the denominators nobody computes:
premium-to-income ratio (the budget half of the 10/10 rule) and how much
of every premium yuan flows into savings-type products that protect
nothing. The gate only respects the heaviest line: a bare pillar
(life/CI/medical at zero) is EXPOSED, exit 4.

Honesty clauses: targets are common-knowledge priors, not actuarial
advice; the tool does not know market premiums — gaps are ranked as
"what to fix first", never "what it will cost"; savings-type policies
stay out of the protection ledger but inside the premium ledger, named;
this tool audits the floor, it does not sell umbrellas. Not insurance
advice.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import sys

PROG = "safety_floor.py"

# Target-amount priors: common-knowledge values, not actuarial advice.
# The planner always wins — every one of these is a CLI flag.
DEFAULT_LIFE_YEARS = 10        # life target = income x life_years
DEFAULT_CI_YEARS = 3           # CI target = expense x ci_years
DEFAULT_MEDICAL_FLOOR = 1000000  # medical is binary: at/above floor or bare
DEFAULT_ACCIDENT_YEARS = 5     # accident target = max(income x years, flat)
DEFAULT_ACCIDENT_FLAT = 200000

# Premium-to-income tiers (budget half of the 10/10 rule).
PREMIUM_OK = 0.10
PREMIUM_OVERPAY = 0.15

STATUS_WEIGHT = {"BARE": 0, "THIN": 1, "SHORT": 2, "COVERED": None}
ROLE_WEIGHT = {"beam": 0, "spouse": 1, "adult": 1, "child": 2, "elder": 3}
PERIL_ORDER = ("life", "ci", "medical", "accident")

# Perils a beam member must never stand without — the only lines the gate
# reads. Elder/child CI or medical being bare is listed, never gated.
BEAM_CRITICAL = ("life", "ci", "medical")

ROLE_ALIASES = {
    "beam": "beam", "pillar": "beam", "顶梁柱": "beam",
    "spouse": "spouse", "配偶": "spouse", "太太": "spouse", "丈夫": "spouse",
    "爱人": "spouse", "夫妻": "spouse",
    "adult": "adult", "成人": "adult",
    "child": "child", "kid": "child", "孩子": "child", "子女": "child",
    "儿子": "child", "女儿": "child", "娃": "child",
    "elder": "elder", "parent": "elder", "长辈": "elder", "老人": "elder",
    "母亲": "elder", "父亲": "elder",
}

TYPE_ALIASES = {
    "life": "life", "定期寿险": "life", "终身寿险": "life", "寿险": "life",
    "定期": "life", "终身": "life",
    "ci": "ci", "critical": "ci", "重疾": "ci", "重疾险": "ci", "大病": "ci",
    "medical": "medical", "医疗": "medical", "医疗险": "medical",
    "百万医疗": "medical", "百万医疗险": "medical",
    "accident": "accident", "意外": "accident", "意外险": "accident",
    "other": "other", "储蓄": "other", "储蓄型": "other", "年金": "other",
    "教育金": "other", "增额": "other", "万能": "other", "分红": "other",
    "理财": "other", "其他": "other",
}

FAMILY_COLUMNS = {
    "name": ("成员", "名字", "姓名", "name", "member"),
    "role": ("角色", "role"),
    "income": ("年收入", "收入", "income"),
}
POLICY_COLUMNS = {
    "policy": ("保单", "保单名", "名称", "policy", "name"),
    "insured": ("被保人", "被保险人", "insured", "member"),
    "type": ("险种", "类型", "type"),
    "coverage": ("保额", "coverage"),
    "premium": ("年保费", "保费", "premium"),
}


class Refuse(Exception):
    """Data pathological — exit 3, never a confident guess."""


# ---------------------------------------------------------------- parsing

def parse_money(text, where, field):
    s = (text or "").strip().replace(",", "").replace("，", "")
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        raise Refuse("bad %s %r%s" % (field, text, where))
    if value < 0:
        raise Refuse("%s must be >= 0, got %s%s" % (field, text, where))
    return value


def _read_rows(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return [row for row in csv.reader(fh)
                    if any((cell or "").strip() for cell in row)]
    except FileNotFoundError:
        raise Refuse("file not found: %s" % path)


def _find_columns(header, needed, optional, path):
    cols = {}
    for name in header:
        key = (name or "").strip().lower()
        for canon, aliases in needed.items():
            if key in aliases and canon not in cols:
                cols[canon] = header.index(name)
        for canon, aliases in optional.items():
            if key in aliases and canon not in cols:
                cols[canon] = header.index(name)
    missing = [c for c in needed if c not in cols]
    if missing:
        raise Refuse("%s: missing column(s) %s — headers seen: %s"
                     % (path, "/".join(missing),
                        ",".join(h or "" for h in header)))
    return cols


class Member(object):
    __slots__ = ("name", "role", "income")

    def __init__(self, name, role, income):
        self.name = name
        self.role = role
        self.income = income


class Policy(object):
    __slots__ = ("policy", "insured", "type", "coverage", "premium", "line")

    def __init__(self, policy, insured, type_, coverage, premium, line):
        self.policy = policy
        self.insured = insured
        self.type = type_
        self.coverage = coverage
        self.premium = premium
        self.line = line


def parse_family(path):
    rows = _read_rows(path)
    if not rows:
        raise Refuse("%s: empty family ledger" % path)
    cols = _find_columns(rows[0],
                         {"name": FAMILY_COLUMNS["name"],
                          "role": FAMILY_COLUMNS["role"]},
                         {"income": FAMILY_COLUMNS["income"]},
                         path)
    members = []
    seen = set()
    for i, row in enumerate(rows[1:], start=2):
        where = " (%s line %d)" % (path, i)

        def cell(key):
            return row[cols[key]] if key in cols and cols[key] < len(row) else ""

        name = (cell("name") or "").strip()
        if not name:
            raise Refuse("%s: empty member name%s" % (path, where))
        if name in seen:
            raise Refuse("%s: duplicate member %r%s" % (path, name, where))
        seen.add(name)
        raw_role = (cell("role") or "").strip().lower()
        role = ROLE_ALIASES.get(raw_role)
        if role is None:
            raise Refuse("%s: unknown role %r%s (want 顶梁柱/配偶/成人/孩子/长辈)"
                         % (path, cell("role"), where))
        income = parse_money(cell("income"), where, "income") or 0.0
        members.append(Member(name, role, income))
    return members


def parse_policies(path, members):
    rows = _read_rows(path)
    if not rows:
        raise Refuse("%s: empty policy ledger" % path)
    cols = _find_columns(rows[0],
                         {"policy": POLICY_COLUMNS["policy"],
                          "insured": POLICY_COLUMNS["insured"],
                          "type": POLICY_COLUMNS["type"]},
                         {"coverage": POLICY_COLUMNS["coverage"],
                          "premium": POLICY_COLUMNS["premium"]},
                         path)
    known = {m.name for m in members}
    policies = []
    for i, row in enumerate(rows[1:], start=2):
        where = " (%s line %d)" % (path, i)

        def cell(key):
            return row[cols[key]] if key in cols and cols[key] < len(row) else ""

        name = (cell("policy") or "").strip()
        insured = (cell("insured") or "").strip()
        if insured not in known:
            raise Refuse("%s: insured %r not in family ledger%s"
                         % (path, insured, where))
        raw_type = (cell("type") or "").strip().lower()
        type_ = TYPE_ALIASES.get(raw_type)
        if type_ is None:
            raise Refuse("%s: unknown policy type %r%s "
                         "(want 寿险/重疾/医疗/意外/储蓄型)"
                         % (path, cell("type"), where))
        coverage = parse_money(cell("coverage"), where, "coverage") or 0.0
        premium = parse_money(cell("premium"), where, "premium") or 0.0
        policies.append(Policy(name, insured, type_, coverage, premium, i))
    return policies


# ------------------------------------------------------------------ model

def life_target(member, life_years):
    """Only income-replacing adults carry a life target; everyone else's
    death does not interrupt the family cash flow — shown as '—'."""
    if member.role in ("child", "elder"):
        return 0.0
    return member.income * life_years


def ci_target(expense, ci_years):
    return expense * ci_years


def accident_target(member, accident_years, accident_flat):
    return max(member.income * accident_years, accident_flat)


def coverage_status(peril, have, target, medical_floor):
    if peril == "medical":
        return ("COVERED" if have >= medical_floor else "BARE")
    if target <= 0:
        return None  # no protection need — rendered as '—'
    if have <= 0:
        return "BARE"
    ratio = have / target
    if ratio < 0.5:
        return "THIN"
    if ratio < 1.0:
        return "SHORT"
    return "COVERED"


def build_matrix(members, policies, expense, life_years, ci_years,
                 medical_floor, accident_years, accident_flat):
    """member -> peril -> {have, target, ratio, status}."""
    by_member = {}
    for p in policies:
        if p.type == "other":
            continue  # savings buys no protection; premium ledger handles it
        by_member.setdefault(p.insured, {}).setdefault(
            p.type, 0.0)
        by_member[p.insured][p.type] += p.coverage

    matrix = {}
    for m in members:
        have = by_member.get(m.name, {})
        row = {}
        for peril in PERIL_ORDER:
            if peril == "life":
                target = life_target(m, life_years)
            elif peril == "ci":
                target = ci_target(expense, ci_years)
            elif peril == "medical":
                target = medical_floor
            else:
                target = accident_target(m, accident_years, accident_flat)
            h = have.get(peril, 0.0)
            status = coverage_status(peril, h, target, medical_floor)
            row[peril] = {
                "have": h,
                "target": target,
                "ratio": (h / target if target > 0 else None),
                "status": status,
            }
        matrix[m.name] = row
    return matrix


def premium_ledger(members, policies):
    total = sum(p.premium for p in policies)
    savings = sum(p.premium for p in policies if p.type == "other")
    by_member = {}
    for p in policies:
        by_member[p.insured] = by_member.get(p.insured, 0.0) + p.premium
    by_type = {}
    for p in policies:
        by_type[p.type] = by_type.get(p.type, 0.0) + p.premium
    income = sum(m.income for m in members)
    return {
        "total": total,
        "savings": savings,
        "savings_ratio": (savings / total if total > 0 else None),
        "by_member": by_member,
        "by_type": by_type,
        "income": income,
        "ratio": (total / income if income > 0 else None),
    }


def gap_list(members, matrix):
    entries = []
    roles = {m.name: m.role for m in members}
    for name, row in matrix.items():
        for peril in PERIL_ORDER:
            cell = row[peril]
            if cell["status"] in (None, "COVERED"):
                continue
            entries.append({
                "member": name,
                "role": roles[name],
                "peril": peril,
                "status": cell["status"],
                "have": cell["have"],
                "target": cell["target"],
                "gap": cell["target"] - cell["have"],
                "_s": STATUS_WEIGHT[cell["status"]],
                "_r": ROLE_WEIGHT[roles[name]],
            })
    entries.sort(key=lambda e: (e["_s"], e["_r"], -e["gap"]))
    return entries


def verdict_of(members, matrix, prem, premium_over_line):
    """EXPOSED (bare pillar / overpay) -> 4; CRACKED -> 0; SOLID -> 0."""
    roles = {m.name: m.role for m in members}
    bare_beam = []
    for name, row in matrix.items():
        if roles[name] != "beam":
            continue
        bares = [p for p in BEAM_CRITICAL if row[p]["status"] == "BARE"]
        if bares:
            bare_beam.append((name, bares))
    overpay = premium_over_line
    if bare_beam:
        return "EXPOSED", 4, bare_beam, overpay
    if overpay:
        return "OVERPAID", 4, [], overpay
    for row in matrix.values():
        for peril in PERIL_ORDER:
            if row[peril]["status"] not in (None, "COVERED"):
                return "CRACKED", 0, [], overpay
    return "SOLID", 0, [], overpay


# ------------------------------------------------------------- formatting

def display_width(s):
    """CJK chars occupy two terminal columns — pad by width, not len."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def pad(s, width):
    return s + " " * max(0, width - display_width(s))


def fmt_amount(v):
    return "{:,.0f}".format(v)


def fmt_compact(v):
    if v >= 1000000:
        return "%.2fM" % (v / 1000000.0)
    if v >= 1000:
        return "%.0fk" % (v / 1000.0)
    return "%.0f" % v


def fmt_ratio(ratio):
    return "—" if ratio is None else "%.2f" % ratio


def fmt_cell(cell):
    if cell["status"] is None:
        return "—"
    return "%-7s %s/%s" % (cell["status"], fmt_compact(cell["have"]),
                           fmt_compact(cell["target"]))


def fmt_pct(v):
    return "—" if v is None else "%.1f%%" % (v * 100)


# ---------------------------------------------------------------- renders

def render_report(members, policies, matrix, prem, verdict, exit_code,
                  bare_beam, args, fmt):
    if fmt == "json":
        import json
        roles = {m.name: m.role for m in members}
        return json.dumps({
            "members": [
                {"name": m.name, "role": m.role, "income": m.income}
                for m in members
            ],
            "expense": args.expense,
            "matrix": {
                name: {
                    peril: {
                        "have": round(row[peril]["have"], 2),
                        "target": round(row[peril]["target"], 2),
                        "ratio": (round(row[peril]["ratio"], 4)
                                  if row[peril]["ratio"] is not None else None),
                        "status": row[peril]["status"],
                    }
                    for peril in PERIL_ORDER
                }
                for name, row in matrix.items()
            },
            "premium": {
                "total": round(prem["total"], 2),
                "income": round(prem["income"], 2),
                "ratio": (round(prem["ratio"], 4)
                          if prem["ratio"] is not None else None),
                "savings": round(prem["savings"], 2),
                "savings_ratio": (round(prem["savings_ratio"], 4)
                                  if prem["savings_ratio"] is not None
                                  else None),
            },
            "bare_beam": [
                {"member": n, "perils": bares} for n, bares in bare_beam
            ],
            "verdict": verdict,
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("SAFETY FLOOR · family coverage audit")
    lines.append("")
    counts = {}
    for p in policies:
        counts[p.type] = counts.get(p.type, 0) + 1
    lines.append("family ledger")
    lines.append("  members  : %d (%s)"
                 % (len(members),
                    " · ".join("%s %d" % (r, sum(1 for m in members
                                                 if m.role == r))
                               for r in ("beam", "spouse", "adult",
                                         "child", "elder")
                               if any(m.role == r for m in members))))
    lines.append("  policies : %d (%s)"
                 % (len(policies),
                    " · ".join("%s %d" % (t, counts[t])
                               for t in ("life", "ci", "medical",
                                         "accident", "other")
                               if t in counts)))
    lines.append("  expense  : %s/yr (anchor for CI targets)"
                 % fmt_amount(args.expense))
    lines.append("  income   : %s/yr (household)" % fmt_amount(prem["income"]))
    lines.append("")
    lines.append("coverage matrix (have/target)")
    lines.append("  %s %-8s %-21s %-21s %-21s %s"
                 % (pad("member", 8), "role", "life", "ci", "medical",
                    "accident"))
    for m in members:
        row = matrix[m.name]
        lines.append("  %s %-8s %-21s %-21s %-21s %s"
                     % (pad(m.name, 8), m.role,
                        fmt_cell(row["life"]), fmt_cell(row["ci"]),
                        fmt_cell(row["medical"]), fmt_cell(row["accident"])))
    lines.append("")
    lines.append("premium ledger")
    lines.append("  total premium : %s/yr" % fmt_amount(prem["total"]))
    if prem["ratio"] is None:
        lines.append("  premium ratio : — (household income is zero; the "
                     "budget line needs a denominator)")
    else:
        tier = ("OK" if prem["ratio"] <= PREMIUM_OK
                else "TIGHT" if prem["ratio"] <= PREMIUM_OVERPAY
                else "OVERPAY")
        lines.append("  premium ratio : %s of income · %s"
                     % (fmt_pct(prem["ratio"]), tier))
    if prem["savings"] > 0:
        lines.append("  savings-type  : %s/yr = %s of every premium yuan "
                     "(buys no protection)"
                     % (fmt_amount(prem["savings"]),
                        fmt_pct(prem["savings_ratio"])))
    feeds = sorted(prem["by_member"].items(), key=lambda kv: -kv[1])
    if prem["total"] > 0 and feeds:
        lines.append("  premium feeds : %s"
                     % " · ".join("%s %s" % (name, fmt_pct(v / prem["total"]))
                                  for name, v in feeds))
    lines.append("")
    lines.append(render_verdict_lines(members, matrix, prem, verdict,
                                      bare_beam))
    return "\n".join(lines), exit_code


def render_verdict_lines(members, matrix, prem, verdict, bare_beam):
    roles = {m.name: m.role for m in members}
    if verdict == "EXPOSED":
        parts = []
        for name, bares in bare_beam:
            parts.append("%s: %s" % (
                name, ", ".join("%s (0 of %s)"
                                % (p, fmt_amount(matrix[name][p]["target"]))
                                for p in bares)))
        lines = ["verdict: EXPOSED — the pillar stands bare (%s)."
                 % "; ".join(parts),
                 "the day the pillar falls, this family lands on nothing. "
                 "exit 4"]
        return "\n".join(lines)
    if verdict == "OVERPAID":
        return ("verdict: OVERPAID — premium ratio %s of income is past the "
                "%s line: this is buying wrong, not buying little. exit 4"
                % (fmt_pct(prem["ratio"]), fmt_pct(PREMIUM_OVERPAY)))
    if verdict == "CRACKED":
        return ("verdict: CRACKED — no bare pillar, but some lines sit below "
                "target. see gaps for the order to fix them. exit 0")
    return "verdict: SOLID — every required line covered. keep the floor dry."


def render_gaps(members, matrix, gaps, args, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "expense": args.expense,
            "gaps": [
                {"member": g["member"], "role": g["role"],
                 "peril": g["peril"], "status": g["status"],
                 "have": round(g["have"], 2),
                 "target": round(g["target"], 2),
                 "gap": round(g["gap"], 2)}
                for g in gaps
            ],
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("gap list — what to fix first "
                 "(bare before thin, pillar before everyone)")
    lines.append("")
    if not gaps:
        lines.append("  nothing below target — the floor holds.")
        return "\n".join(lines), 0
    lines.append("  %-3s %s %-8s %-8s %-8s %12s %12s %12s"
                 % ("#", pad("member", 8), "role", "peril", "status",
                    "have", "target", "gap"))
    for i, g in enumerate(gaps, start=1):
        lines.append("  %-3d %s %-8s %-8s %-8s %12s %12s %12s"
                     % (i, pad(g["member"], 8), g["role"], g["peril"],
                        g["status"],
                        fmt_amount(g["have"]), fmt_amount(g["target"]),
                        fmt_amount(g["gap"])))
    return "\n".join(lines), 0


def render_premium(members, prem, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "total": round(prem["total"], 2),
            "income": round(prem["income"], 2),
            "ratio": (round(prem["ratio"], 4)
                      if prem["ratio"] is not None else None),
            "savings": round(prem["savings"], 2),
            "savings_ratio": (round(prem["savings_ratio"], 4)
                              if prem["savings_ratio"] is not None else None),
            "by_member": {k: round(v, 2)
                          for k, v in prem["by_member"].items()},
            "by_type": {k: round(v, 2)
                        for k, v in prem["by_type"].items()},
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("premium ledger — what every yuan buys")
    lines.append("")
    lines.append("  total premium : %s/yr" % fmt_amount(prem["total"]))
    lines.append("  household inc : %s/yr" % fmt_amount(prem["income"]))
    if prem["ratio"] is None:
        lines.append("  premium ratio : — (no income denominator)")
    else:
        tier = ("OK" if prem["ratio"] <= PREMIUM_OK
                else "TIGHT" if prem["ratio"] <= PREMIUM_OVERPAY
                else "OVERPAY")
        lines.append("  premium ratio : %s of income · %s "
                       "(<= %s OK · > %s OVERPAY, exit 4)"
                       % (fmt_pct(prem["ratio"]), tier,
                          fmt_pct(PREMIUM_OK), fmt_pct(PREMIUM_OVERPAY)))
    if prem["savings"] > 0:
        lines.append("  savings-type  : %s/yr = %s of every premium yuan — "
                     "annuities and education funds buy no protection"
                     % (fmt_amount(prem["savings"]),
                        fmt_pct(prem["savings_ratio"])))
    if prem["total"] > 0:
        feeds = sorted(prem["by_member"].items(), key=lambda kv: -kv[1])
        lines.append("  premium feeds : %s"
                     % " · ".join("%s %s" % (name, fmt_pct(v / prem["total"]))
                                  for name, v in feeds))
        types = sorted(prem["by_type"].items(), key=lambda kv: -kv[1])
        lines.append("  by peril      : %s"
                     % " · ".join("%s %s" % (t, fmt_amount(v))
                                  for t, v in types))
    return "\n".join(lines), (4 if prem["ratio"] is not None
                              and prem["ratio"] > PREMIUM_OVERPAY else 0)


# ------------------------------------------------------------------ main

def resolve_args(args, need_expense=True):
    members = parse_family(args.family)
    policies = parse_policies(args.policies, members)
    expense = None
    if need_expense:
        if args.expense is None:
            raise Refuse("--expense is required: CI targets are anchored on "
                         "annual family spend — no anchor, no target")
        if args.expense <= 0:
            raise Refuse("--expense must be > 0, got %s" % args.expense)
        expense = args.expense
    return members, policies, expense


def cmd_report(args):
    members, policies, expense = resolve_args(args)
    matrix = build_matrix(members, policies, expense, args.life_years,
                          args.ci_years, args.medical_floor,
                          args.accident_years, args.accident_flat)
    prem = premium_ledger(members, policies)
    overpay = prem["ratio"] is not None and prem["ratio"] > PREMIUM_OVERPAY
    verdict, exit_code, bare_beam, _ = verdict_of(members, matrix, prem,
                                                  overpay)
    text, code = render_report(members, policies, matrix, prem, verdict,
                               exit_code, bare_beam, args, args.format)
    print(text)
    return code


def cmd_gaps(args):
    members, policies, expense = resolve_args(args)
    matrix = build_matrix(members, policies, expense, args.life_years,
                          args.ci_years, args.medical_floor,
                          args.accident_years, args.accident_flat)
    gaps = gap_list(members, matrix)
    text, code = render_gaps(members, matrix, gaps, args, args.format)
    print(text)
    return code


def cmd_premium(args):
    members, policies, _ = resolve_args(args, need_expense=False)
    prem = premium_ledger(members, policies)
    text, code = render_premium(members, prem, args.format)
    print(text)
    return code


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="兜底 · Safety Floor — family coverage-gap ledger.")
    sub = parser.add_subparsers(dest="command")

    def add_common(p, need_expense=True):
        p.add_argument("family", help="family CSV (成员,角色,年收入)")
        p.add_argument("policies", help="policies CSV (保单,被保人,险种,保额,年保费)")
        if need_expense:
            p.add_argument("--expense", type=float, default=None,
                           help="annual family spend (CI target anchor)")
        p.add_argument("--life-years", dest="life_years", type=float,
                       default=DEFAULT_LIFE_YEARS,
                       help="life target = income x N (default %s)"
                            % DEFAULT_LIFE_YEARS)
        p.add_argument("--ci-years", dest="ci_years", type=float,
                       default=DEFAULT_CI_YEARS,
                       help="CI target = expense x N (default %s)"
                            % DEFAULT_CI_YEARS)
        p.add_argument("--medical-floor", dest="medical_floor", type=float,
                       default=DEFAULT_MEDICAL_FLOOR,
                       help="medical binary floor (default %s)"
                            % DEFAULT_MEDICAL_FLOOR)
        p.add_argument("--accident-years", dest="accident_years", type=float,
                       default=DEFAULT_ACCIDENT_YEARS,
                       help="accident = max(income x N, flat) (default %s)"
                            % DEFAULT_ACCIDENT_YEARS)
        p.add_argument("--accident-flat", dest="accident_flat", type=float,
                       default=DEFAULT_ACCIDENT_FLAT,
                       help="accident flat floor (default %s)"
                            % DEFAULT_ACCIDENT_FLAT)
        p.add_argument("--format", choices=("text", "json"), default="text")

    p = sub.add_parser("report", help="full coverage matrix + verdict gate")
    add_common(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("gaps", help="ranked list: what to fix first")
    add_common(p)
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("premium", help="premium-to-income + savings share")
    add_common(p, need_expense=False)
    p.set_defaults(func=cmd_premium)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except Refuse as exc:
        print("refuse: %s" % exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
