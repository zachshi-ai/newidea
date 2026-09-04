#!/usr/bin/env python3
"""种草账 · Want Ledger.

Every ledger in your life starts at the purchase: the wardrobe ledger
counts wears, the fridge ledger counts waste, the secondhand ledger counts
recovery. Nobody keeps a ledger of the WANTING — the stretch between "刷到
了好想要" and either checkout or forgetting. That stretch is where impulse
lives, and it is statistically invisible: you cannot say what fraction of
your desires die young, whether buying fast makes you regret more than
buying slow, or how much money your least reliable desires have burned.

want-ledger reads one hand-kept ledger:

  grass.csv — 种草日,品名,价位[,标签][,结局,结局日,后悔][,备注]
              one row per sprout of desire. 结局 empty = still growing
              (在长); 拔草/bought = you bought it; 枯草/passed = you
              didn't, and the want died. 后悔 (y/n) is backfilled on
              bought rows — the skin you put in the game afterwards.

and reports what no checkout page will ever show you:

  report    the desire census: half-life of a want, 30-day survival rate,
            the two-arm regret comparison (impulse vs deliberate buys),
            the impulse tuition bill, per-tag profiles
            (REGRET-HEAVY / SETTLED, exit 4 on REGRET-HEAVY)
  check     the cooling-off gate for tonight's sprout: is it old enough to
            vote, and what does your own history testify
            (STILL COOLING exit 4 / DECIDE NOW exit 0)
  doctor    data physical exam before you trust any of the above

Honesty clauses: the ledger only knows what you backfill — an un-graded
regret is a missing lab result, never an assumed happy ending; prices are
your stated price-tags, not audited receipts; small samples are marked
THIN and refuse to conclude instead of performing confidence; the gate
blocks nothing — it only tells you what your own past testifies, and the
vote is always yours.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import statistics
import sys
from datetime import date

PROG = "want_ledger.py"

# Bought-and-regretted money as a share of all bought money at/above this
# line trips REGRET-HEAVY (exit 4). A value, not a constant of nature.
DEFAULT_TUITION_LINE = 30.0

# A sprout younger than this is still cooling (check gate, days).
DEFAULT_COOL = 14

# A buy resolved within this many days of seeding counts as impulse.
IMPULSE_DAYS = 7

# Minimum data for each claim.
MIN_ITEMS = 5          # whole-ledger: fewer sprouts = nothing to audit
MIN_HALFLIFE = 3       # passed items to state a half-life
MIN_SURVIVAL = 5       # 30d-observable items to state a survival rate
MIN_ARM = 5            # regret-graded buys per arm to compare arms
MIN_TUITION = 8        # priced buys before the tuition gate may fire
GHOST_DAYS = 90        # a still-growing sprout older than this is a ghost

STATUS_BOUGHT, STATUS_PASSED, STATUS_STILL = "BOUGHT", "PASSED", "STILL"
STATUS_ALIASES = {
    "bought": STATUS_BOUGHT, "buy": STATUS_BOUGHT, "bought it": STATUS_BOUGHT,
    "买": STATUS_BOUGHT, "买了": STATUS_BOUGHT, "拔草": STATUS_BOUGHT,
    "passed": STATUS_PASSED, "drop": STATUS_PASSED, "dropped": STATUS_PASSED,
    "skip": STATUS_PASSED, "算了": STATUS_PASSED, "枯": STATUS_PASSED,
    "枯草": STATUS_PASSED, "没买": STATUS_PASSED,
    "still": STATUS_STILL, "在长": STATUS_STILL, "长草": STATUS_STILL,
}
REGRET_YES = {"y", "yes", "1", "是", "后悔", "真后悔"}
REGRET_NO = {"n", "no", "0", "否", "不后悔", "没后悔"}

COLUMNS = {
    "seed": ("种草日", "日期", "seed", "seeded", "date"),
    "item": ("品名", "item", "name", "东西"),
    "price": ("价位", "价格", "price", "cost"),
    "tag": ("标签", "tag", "category", "类"),
    "status": ("结局", "status", "outcome"),
    "resolved": ("结局日", "resolved", "decided"),
    "regret": ("后悔", "regret"),
    "note": ("备注", "note", "说明"),
}


class Refuse(Exception):
    """Data too thin or malformed to answer — exit 3, never a guess."""


# ---------------------------------------------------------------- parsing

def parse_date(text, where=""):
    s = (text or "").strip()
    for sep in ("-", "/", "."):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    return date(int(parts[0]), int(parts[1]), int(parts[2]))
                except ValueError:
                    break
    raise Refuse("bad date %r%s (want YYYY-MM-DD)" % (text, where))


def parse_price(text, where):
    s = (text or "").strip().replace(",", "").replace("，", "")
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        raise Refuse("bad price %r%s" % (text, where))
    if value < 0:
        raise Refuse("price must be >= 0, got %s%s" % (text, where))
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


class Want(object):
    """One sprout of desire, from seed to resolution (or still growing)."""

    __slots__ = ("seed", "item", "price", "tag", "status", "resolved",
                 "regret", "note", "line")

    def __init__(self, seed, item, price, tag, status, resolved, regret,
                 note, line):
        self.seed = seed
        self.item = item
        self.price = price
        self.tag = tag
        self.status = status
        self.resolved = resolved
        self.regret = regret
        self.note = note
        self.line = line

    @property
    def unit(self):
        return self.tag if self.tag else "(untagged)"


def parse_wants(path):
    rows = _read_rows(path)
    if not rows:
        raise Refuse("%s: empty ledger" % path)
    cols = _find_columns(rows[0],
                         {"seed": COLUMNS["seed"],
                          "item": COLUMNS["item"]},
                         {"price": COLUMNS["price"],
                          "tag": COLUMNS["tag"],
                          "status": COLUMNS["status"],
                          "resolved": COLUMNS["resolved"],
                          "regret": COLUMNS["regret"],
                          "note": COLUMNS["note"]},
                         path)
    wants = []
    for i, row in enumerate(rows[1:], start=2):
        where = " (%s line %d)" % (path, i)

        def cell(key):
            idx = cols.get(key)
            if idx is None or idx >= len(row):
                return ""
            return (row[idx] or "").strip()

        seed = parse_date(cell("seed"), where)
        item = cell("item")
        if not item:
            raise Refuse("%s: empty 品名%s" % (path, where))
        price = parse_price(cell("price"), where)
        tag = cell("tag")

        raw_status = cell("status").lower()
        if not raw_status:
            status = STATUS_STILL
        else:
            status = STATUS_ALIASES.get(raw_status)
            if status is None:
                raise Refuse("%s: unknown 结局 %r (want 拔草/枯草/在长 or "
                             "empty)%s" % (path, cell("status"), where))

        resolved = None
        if cell("resolved"):
            resolved = parse_date(cell("resolved"), where)

        regret = None
        raw_regret = cell("regret").lower()
        if raw_regret:
            if raw_regret in REGRET_YES:
                regret = True
            elif raw_regret in REGRET_NO:
                regret = False
            else:
                raise Refuse("%s: bad 后悔 %r (want y/n)%s"
                             % (path, cell("regret"), where))

        wants.append(Want(seed, item, price, tag, status, resolved, regret,
                          cell("note"), i))
    wants.sort(key=lambda w: w.seed)
    return wants


def validate_wants(wants):
    for w in wants:
        if w.status == STATUS_STILL:
            if w.resolved is not None:
                raise Refuse("line %d: %r is still growing (在长) but has a "
                             "resolved date %s — clear 结局 or fill 结局"
                             % (w.line, w.item, w.resolved.isoformat()))
        else:
            if w.resolved is None:
                raise Refuse("line %d: %r is %s but has no 结局日 — a decided "
                             "want needs its decision date"
                             % (w.line, w.item, w.status))
            if w.resolved < w.seed:
                raise Refuse("line %d: %r resolved (%s) before it was seeded "
                             "(%s) — time travel refused"
                             % (w.line, w.item, w.resolved.isoformat(),
                                w.seed.isoformat()))
        if w.regret is not None and w.status != STATUS_BOUGHT:
            raise Refuse("line %d: %r carries a 后悔 grade but was never "
                         "bought — 后悔 grades apply to 拔草 rows only "
                         "(passed wants don't regret, they just die)"
                         % (w.line, w.item))


# ------------------------------------------------------------------- time

def ledger_as_of(wants, as_of_text):
    """Deterministic default: the ledger's own last day of activity.

    Explicit --as-of may travel back (audit the census as it looked then:
    wants resolved later are censored as still-growing), but never before
    the first sprout — nothing was growing yet.
    """
    if as_of_text is None:
        return max([w.seed for w in wants]
                   + [w.resolved for w in wants if w.resolved is not None])
    day = parse_date(as_of_text, " (--as-of)")
    first = min(w.seed for w in wants)
    if day < first:
        raise Refuse("--as-of %s predates the first sprout %s — nothing was "
                     "growing yet" % (day.isoformat(), first.isoformat()))
    return day


def visible_wants(wants, as_of):
    """Seeded by as_of; resolved later counts as still-growing at as_of."""
    seen, future = [], 0
    for w in wants:
        if w.seed > as_of:
            future += 1
            continue
        if w.resolved is not None and w.resolved > as_of:
            seen.append(Want(w.seed, w.item, w.price, w.tag, STATUS_STILL,
                             None, w.regret, w.note, w.line))
        else:
            seen.append(w)
    return seen, future


# ------------------------------------------------------------------- math

def half_life(wants):
    """Median days-from-seed-to-death among PASSED wants (None if thin)."""
    lifetimes = [(w.resolved - w.seed).days for w in wants
                 if w.status == STATUS_PASSED]
    if len(lifetimes) < MIN_HALFLIFE:
        return None, lifetimes
    return statistics.median(lifetimes), lifetimes


def survival_30(wants, as_of):
    """Share of wants still wanted on day 30, among those observable.

    Observable: resolved at any age (we see whether day 30 arrived while
    still wanted), or still-growing with age >= 30. Young stills wait.
    """
    observed = survived = 0
    for w in wants:
        age_now = (as_of - w.seed).days
        if w.status == STATUS_STILL:
            if age_now >= 30:
                observed += 1
                survived += 1
        else:
            observed += 1
            if (w.resolved - w.seed).days >= 30:
                survived += 1
    if observed < MIN_SURVIVAL:
        return None, observed
    return survived / float(observed), observed


def regret_arms(wants):
    """Impulse (<=7d seed-to-buy) vs deliberate (>7d) regret rates.

    Un-graded regrets are excluded from the rates and counted separately —
    a missing grade is missing data, never a happy ending.
    """
    arms = {}
    for name, quick in (("impulse", True), ("deliberate", False)):
        members = [w for w in wants if w.status == STATUS_BOUGHT
                   and ((w.resolved - w.seed).days <= IMPULSE_DAYS) == quick]
        graded = [w for w in members if w.regret is not None]
        rate = (sum(1 for w in graded if w.regret) / float(len(graded))
                if graded else None)
        arms[name] = {
            "n": len(members),
            "graded": len(graded),
            "ungraded": len(members) - len(graded),
            "regrets": sum(1 for w in graded if w.regret),
            "rate": rate,
        }
    return arms


def money(wants):
    """Tuition (bought & regretted) vs spent vs saved-by-wilting."""
    spent = sum(w.price for w in wants
                if w.status == STATUS_BOUGHT and w.price is not None)
    tuition = sum(w.price for w in wants
                  if w.status == STATUS_BOUGHT and w.regret
                  and w.price is not None)
    saved = sum(w.price for w in wants
                if w.status == STATUS_PASSED and w.price is not None)
    bought_priced = sum(1 for w in wants
                        if w.status == STATUS_BOUGHT and w.price is not None)
    unpriced = sum(1 for w in wants if w.price is None)
    return {
        "spent": spent,
        "tuition": tuition,
        "saved": saved,
        "bought_priced": bought_priced,
        "unpriced": unpriced,
        "ratio": (tuition / spent) if spent > 0 else None,
    }


def tag_profiles(wants):
    """Per-tag census: n, wilting half-life, regret share, tuition."""
    tags = {}
    for w in wants:
        tags.setdefault(w.unit, []).append(w)
    profiles = []
    for tag in sorted(tags):
        members = tags[tag]
        tHalf, _ = half_life(members)
        graded = [w for w in members
                  if w.status == STATUS_BOUGHT and w.regret is not None]
        tuition = sum(w.price for w in members
                      if w.status == STATUS_BOUGHT and w.regret
                      and w.price is not None)
        profiles.append({
            "tag": tag,
            "n": len(members),
            "bought": sum(1 for w in members if w.status == STATUS_BOUGHT),
            "passed": sum(1 for w in members if w.status == STATUS_PASSED),
            "still": sum(1 for w in members if w.status == STATUS_STILL),
            "half_life": tHalf,
            "regret_rate": (sum(1 for w in graded if w.regret)
                            / float(len(graded))) if graded else None,
            "tuition": tuition,
        })
    return profiles


# ---------------------------------------------------------------- verdict

def build_report(wants, as_of, tuition_line):
    seen, future = visible_wants(wants, as_of)
    if len(seen) < MIN_ITEMS:
        raise Refuse("only %d want(s) seeded by as-of %s — a desire audit "
                     "needs at least %d sprouts to say anything"
                     % (len(seen), as_of.isoformat(), MIN_ITEMS))
    t_half, lifetimes = half_life(seen)
    survival, observed = survival_30(seen, as_of)
    arms = regret_arms(seen)
    purse = money(seen)
    profiles = tag_profiles(seen)
    ghosts = [w for w in seen if w.status == STATUS_STILL
              and (as_of - w.seed).days > GHOST_DAYS]
    comparable = (arms["impulse"]["rate"] is not None
                  and arms["deliberate"]["rate"] is not None
                  and arms["impulse"]["graded"] >= MIN_ARM
                  and arms["deliberate"]["graded"] >= MIN_ARM)
    gate_fires = (purse["ratio"] is not None
                  and purse["bought_priced"] >= MIN_TUITION)
    if gate_fires and purse["ratio"] * 100.0 >= tuition_line:
        verdict = "REGRET-HEAVY"
    else:
        verdict = "SETTLED"
    return {
        "as_of": as_of,
        "total": len(wants),
        "future": future,
        "seen": seen,
        "t_half": t_half,
        "lifetimes": lifetimes,
        "survival": survival,
        "observed": observed,
        "arms": arms,
        "purse": purse,
        "profiles": profiles,
        "ghosts": ghosts,
        "comparable": comparable,
        "tuition_line": tuition_line,
        "verdict": verdict,
    }


# ----------------------------------------------------------- formatting

def fmt_money(v, signed=False):
    text = "{:,.2f}".format(abs(v))
    if v < 0:
        return "-" + text
    return ("+" + text) if signed else text


def fmt_pct(v, signed=True):
    if v is None:
        return "—"
    return "{:+,.1f}%".format(v * 100) if signed else "{:,.1f}%".format(v * 100)


# --------------------------------------------------------------- renders

def render_report(rp, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "as_of": rp["as_of"].isoformat(),
            "wants_seeded": len(rp["seen"]),
            "future_wants": rp["future"],
            "counts": {
                "bought": sum(1 for w in rp["seen"]
                              if w.status == STATUS_BOUGHT),
                "passed": sum(1 for w in rp["seen"]
                              if w.status == STATUS_PASSED),
                "still": sum(1 for w in rp["seen"]
                             if w.status == STATUS_STILL),
            },
            "half_life_days": rp["t_half"],
            "half_life_n": len(rp["lifetimes"]),
            "survival_30": (round(rp["survival"], 6)
                            if rp["survival"] is not None else None),
            "survival_observable": rp["observed"],
            "arms": {
                name: {
                    "bought": a["n"],
                    "graded": a["graded"],
                    "ungraded": a["ungraded"],
                    "regrets": a["regrets"],
                    "regret_rate": (round(a["rate"], 6)
                                    if a["rate"] is not None else None),
                } for name, a in rp["arms"].items()
            },
            "money": {
                "spent": round(rp["purse"]["spent"], 2),
                "tuition": round(rp["purse"]["tuition"], 2),
                "saved": round(rp["purse"]["saved"], 2),
                "tuition_ratio_pct": (round(rp["purse"]["ratio"] * 100, 4)
                                      if rp["purse"]["ratio"] is not None
                                      else None),
                "unpriced": rp["purse"]["unpriced"],
            },
            "tags": [
                {"tag": p["tag"], "n": p["n"], "bought": p["bought"],
                 "passed": p["passed"], "still": p["still"],
                 "half_life_days": p["half_life"],
                 "regret_rate": (round(p["regret_rate"], 6)
                                 if p["regret_rate"] is not None else None),
                 "tuition": round(p["tuition"], 2)}
                for p in rp["profiles"]
            ],
            "ghosts": [w.item for w in rp["ghosts"]],
            "tuition_line_pct": rp["tuition_line"],
            "verdict": rp["verdict"],
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    purse = rp["purse"]
    arms = rp["arms"]
    lines = []
    lines.append("WANT LEDGER · desire audit — as-of %s"
                 % rp["as_of"].isoformat())
    lines.append("")
    counts = {s: sum(1 for w in rp["seen"] if w.status == s)
              for s in (STATUS_BOUGHT, STATUS_PASSED, STATUS_STILL)}
    lines.append("the census")
    lines.append("  sprouts   : %d seeded (%d bought · %d wilted · %d still "
                 "growing)%s"
                 % (len(rp["seen"]), counts[STATUS_BOUGHT],
                    counts[STATUS_PASSED], counts[STATUS_STILL],
                    (" · %d not yet seeded by as-of" % rp["future"])
                    if rp["future"] else ""))
    if rp["t_half"] is not None:
        lines.append("  half-life : a want lives %.1f days before it wilts "
                 "(median of %d wilted)" % (rp["t_half"],
                                            len(rp["lifetimes"])))
    else:
        lines.append("  half-life : — (only %d wilted want(s) — need %d; "
                     "your desires have not reported enough deaths yet)"
                     % (len(rp["lifetimes"]), MIN_HALFLIFE))
    if rp["survival"] is not None:
        lines.append("  30d survival: %s of wants live past day 30 "
                     "(%d of %d observable)"
                     % (fmt_pct(rp["survival"], signed=False),
                        round(rp["survival"] * rp["observed"]),
                        rp["observed"]))
    else:
        lines.append("  30d survival: — (only %d observable — need %d)"
                     % (rp["observed"], MIN_SURVIVAL))
    lines.append("")
    lines.append("two arms of you — regret by buying speed")
    for name, label in (("impulse", "impulse    (bought within %2d days)"
                         % IMPULSE_DAYS),
                        ("deliberate", "deliberate (bought after   %2d days)"
                         % IMPULSE_DAYS)):
        a = arms[name]
        if a["graded"]:
            lines.append("  %s  %2d bought, %d graded: %s regret it%s"
                         % (label, a["n"], a["graded"],
                            fmt_pct(a["rate"], signed=False),
                            (", %d grade(s) missing" % a["ungraded"])
                            if a["ungraded"] else ""))
        else:
            lines.append("  %s  %2d bought, none graded — no testimony"
                         % (label, a["n"]))
    if rp["comparable"]:
        gap = arms["impulse"]["rate"] - arms["deliberate"]["rate"]
        if gap > 0:
            lines.append("  verdict on arms: your hands buy faster than "
                         "your heart approves — impulse regret %s vs "
                         "deliberate %s. Slow is your cheaper gear."
                         % (fmt_pct(arms["impulse"]["rate"], signed=False),
                            fmt_pct(arms["deliberate"]["rate"],
                                    signed=False)))
        elif gap < 0:
            lines.append("  verdict on arms: your deliberation buys more "
                         "regret than your impulses do (%s vs %s) — "
                         "waiting is not automatically wisdom."
                         % (fmt_pct(arms["deliberate"]["rate"],
                                    signed=False),
                            fmt_pct(arms["impulse"]["rate"], signed=False)))
        else:
            lines.append("  verdict on arms: dead even — speed is not your "
                         "problem.")
    else:
        lines.append("  verdict on arms: THIN — need %d graded buy(s) per "
                     "arm to put your two selves on trial."
                     % MIN_ARM)
    lines.append("")
    lines.append("the tuition bill")
    if purse["bought_priced"]:
        lines.append("  bought     : %s across %d priced purchase(s)%s"
                     % (fmt_money(purse["spent"]), purse["bought_priced"],
                        (", %d want(s) unpriced and left out of all money "
                         "accounts" % purse["unpriced"])
                        if purse["unpriced"] else ""))
        if purse["ratio"] is not None:
            lines.append("  tuition    : %s bought in regret — %s of "
                         "everything you bought (line %.0f%%)"
                         % (fmt_money(purse["tuition"]),
                            fmt_pct(purse["ratio"], signed=False),
                            rp["tuition_line"]))
    else:
        lines.append("  bought     : no priced purchases on record")
    if purse["saved"]:
        lines.append("  saved by wilting: %s of wants you let die — the "
                     "cheapest purchases you never made"
                     % fmt_money(purse["saved"]))
    lines.append("")
    lines.append("tag profiles (worst tuition first)")
    ranked = sorted(rp["profiles"], key=lambda p: -p["tuition"])
    for p in ranked:
        hl = ("%.1fd" % p["half_life"]) if p["half_life"] is not None else "—"
        rr = fmt_pct(p["regret_rate"], signed=False) \
            if p["regret_rate"] is not None else "—"
        lines.append("  %-10s n=%-2d bought %d · wilted %d · t½ %s · "
                     "regret %s · tuition %s"
                     % (p["tag"][:10], p["n"], p["bought"], p["passed"],
                        hl, rr, fmt_money(p["tuition"])))
    if rp["ghosts"]:
        lines.append("")
        lines.append("ghost sprouts (growing >%d days, never voted on): %s"
                     % (GHOST_DAYS,
                        ", ".join("%s (%dd)" % (w.item,
                                                (rp["as_of"] - w.seed).days)
                                  for w in rp["ghosts"])))
    lines.append("")
    if rp["verdict"] == "REGRET-HEAVY":
        lines.append("verdict: REGRET-HEAVY — %s of what you bought, you "
                     "regret buying: %s of your money went to desires that "
                     "did not survive their own checkout. The cooling gate "
                     "exists for exactly this ledger."
                     % (fmt_pct(purse["ratio"], signed=False),
                        fmt_money(purse["tuition"])))
        exit_code = 4
    else:
        lines.append("verdict: SETTLED — your regret share %s is inside the "
                     "%.0f%% line. Your wanting is mostly telling the truth; "
                     "keep feeding the ledger."
                     % (fmt_pct(purse["ratio"], signed=False)
                        if purse["ratio"] is not None else "—",
                        rp["tuition_line"]))
        exit_code = 0
    return "\n".join(lines), exit_code


# ----------------------------------------------------------------- check

def build_check(wants, item, price, tag, seeded, today, cool):
    if today < seeded:
        raise Refuse("--today %s predates --seeded %s — the sprout cannot be "
                     "checked before it is planted"
                     % (today.isoformat(), seeded.isoformat()))
    age = (today - seeded).days
    seen, _ = visible_wants(wants, today)
    t_half, _ = half_life(seen)
    survival, observed = survival_30(seen, today)
    arms = regret_arms(seen)
    purse = money(seen)
    if age < cool:
        verdict = "STILL_COOLING"
        due = seeded.toordinal() + cool
        due_date = date.fromordinal(due)
    else:
        verdict = "DECIDE_NOW"
        due_date = None
    return {
        "item": item,
        "price": price,
        "tag": tag if tag else "(untagged)",
        "seeded": seeded,
        "today": today,
        "age": age,
        "cool": cool,
        "due": due_date,
        "t_half": t_half,
        "survival": survival,
        "observed": observed,
        "arms": arms,
        "purse": purse,
        "verdict": verdict,
    }


def render_check(ck, fmt):
    if fmt == "json":
        import json
        return json.dumps({
            "item": ck["item"],
            "price": ck["price"],
            "tag": ck["tag"],
            "seeded": ck["seeded"].isoformat(),
            "today": ck["today"].isoformat(),
            "age_days": ck["age"],
            "cool_days": ck["cool"],
            "due": ck["due"].isoformat() if ck["due"] else None,
            "half_life_days": ck["t_half"],
            "survival_30": (round(ck["survival"], 6)
                            if ck["survival"] is not None else None),
            "survival_observable": ck["observed"],
            "impulse_regret_rate": (round(ck["arms"]["impulse"]["rate"], 6)
                                    if ck["arms"]["impulse"]["rate"]
                                    is not None else None),
            "deliberate_regret_rate": (round(ck["arms"]["deliberate"]["rate"],
                                             6)
                                       if ck["arms"]["deliberate"]["rate"]
                                       is not None else None),
            "tuition_ratio_pct": (round(ck["purse"]["ratio"] * 100, 4)
                                  if ck["purse"]["ratio"] is not None
                                  else None),
            "verdict": ck["verdict"],
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("WANT LEDGER · cooling gate — %s" % ck["item"])
    lines.append("")
    lines.append("  sprout    : %s · %s · seeded %s, age %d day(s)"
                 % (ck["item"], fmt_money(ck["price"]) if ck["price"]
                    is not None else "unpriced",
                    ck["seeded"].isoformat(), ck["age"]))
    lines.append("  evidence  : %s"
                 % (a_desire_line(ck)))
    lines.append("  testimony : %s" % a_arm_line(ck))
    lines.append("")
    if ck["verdict"] == "STILL_COOLING":
        lines.append("verdict: STILL COOLING — age %d < cooling period %d. "
                     "Come back on %s and vote. Your ledger says most of "
                     "you will have forgotten why you wanted this."
                     % (ck["age"], ck["cool"], ck["due"].isoformat()))
        exit_code = 4
    else:
        lines.append("verdict: DECIDE NOW — the cooling period is served "
                     "(age %d >= %d). The evidence is on the table; the "
                     "vote is yours. Whatever you decide, backfill the 后悔 "
                     "column — that grade is the next vote's evidence."
                     % (ck["age"], ck["cool"]))
        exit_code = 0
    return "\n".join(lines), exit_code


def a_desire_line(ck):
    if ck["survival"] is not None:
        return ("of your past wants, %s lived past day 30 (%d observable)"
                % (fmt_pct(ck["survival"], signed=False), ck["observed"]))
    if ck["t_half"] is not None:
        return ("your wilted wants lived %.1f days (median) — too few to "
                "state a 30d survival rate" % ck["t_half"])
    return ("too few resolved wants in the ledger to testify")


def a_arm_line(ck):
    parts = []
    for name, label in (("impulse", "impulse"), ("deliberate", "deliberate")):
        a = ck["arms"][name]
        if a["rate"] is not None and a["graded"]:
            parts.append("%s regret %s (n=%d)"
                         % (label, fmt_pct(a["rate"], signed=False),
                            a["graded"]))
        else:
            parts.append("%s ungraded" % label)
    if ck["purse"]["ratio"] is not None and ck["purse"]["bought_priced"]:
        parts.append("tuition %s of spending"
                     % fmt_pct(ck["purse"]["ratio"], signed=False))
    return " · ".join(parts)


# ---------------------------------------------------------------- doctor

def doctor_problems(wants):
    problems = []
    for w in wants:
        if w.status == STATUS_BOUGHT and w.regret is None and w.resolved \
                is not None and (w.resolved - w.seed).days >= 7:
            problems.append(("WARN",
                             "line %d: %r took %d day(s) from seed to buy "
                             "and the 后悔 grade is still blank — an "
                             "ungraded regret is a missing lab result"
                             % (w.line, w.item, (w.resolved - w.seed).days)))
        if w.status == STATUS_BOUGHT and w.price is None:
            problems.append(("WARN",
                             "line %d: %r was bought with no price — the "
                             "tuition bill cannot count it"
                             % (w.line, w.item)))
    from collections import Counter
    seeds = Counter((w.item, w.seed) for w in wants)
    for (item, seed), n in seeds.items():
        if n > 1:
            problems.append(("WARN",
                             "%r seeded on %s appears %d times — sprout it "
                             "once, update its row instead"
                             % (item, seed.isoformat(), n)))
    if len(wants) < MIN_ITEMS:
        problems.append(("FATAL",
                         "%d want(s) on record — a desire audit needs at "
                         "least %d" % (len(wants), MIN_ITEMS)))
        return problems
    passed = sum(1 for w in wants if w.status == STATUS_PASSED)
    if passed < MIN_HALFLIFE:
        problems.append(("WARN",
                         "only %d wilted want(s) — the half-life will "
                         "refuse to conclude" % passed))
    bought = [w for w in wants if w.status == STATUS_BOUGHT]
    graded = sum(1 for w in bought if w.regret is not None)
    if bought and graded < 2 * MIN_ARM:
        problems.append(("WARN",
                         "only %d of %d buy(s) carry a 后悔 grade — the "
                         "two-arm comparison will stay THIN"
                         % (graded, len(bought))))
    return problems


def render_doctor(wants, problems, fmt):
    fatal = [p for p in problems if p[0] == "FATAL"]
    warns = [p for p in problems if p[0] == "WARN"]
    if fmt == "json":
        import json
        return json.dumps({
            "wants": len(wants),
            "fatal": [m for _, m in fatal],
            "warnings": [m for _, m in warns],
            "healthy": not fatal,
        }, ensure_ascii=False, indent=2, sort_keys=True), 0

    lines = []
    lines.append("doctor — data physical exam")
    lines.append("")
    counts = {s: sum(1 for w in wants if w.status == s)
              for s in (STATUS_BOUGHT, STATUS_PASSED, STATUS_STILL)}
    lines.append("  sprouts : %d rows (%d bought · %d wilted · %d growing)"
                 % (len(wants), counts[STATUS_BOUGHT],
                    counts[STATUS_PASSED], counts[STATUS_STILL]))
    for _, msg in warns:
        lines.append("  warn    : %s" % msg)
    for _, msg in fatal:
        lines.append("  FATAL   : %s" % msg)
    lines.append("")
    if fatal:
        lines.append("verdict: UNHEALTHY — fix the FATAL rows before trusting "
                     "any audit.")
        return "\n".join(lines), 3
    if warns:
        lines.append("verdict: USABLE WITH NOTES — every note is disclosed "
                     "in the audit.")
        return "\n".join(lines), 0
    lines.append("verdict: HEALTHY — this desire ledger deserves the audit.")
    return "\n".join(lines), 0


# ------------------------------------------------------------------ main

def cmd_report(args):
    wants = parse_wants(args.grass)
    validate_wants(wants)
    as_of = ledger_as_of(wants, args.as_of)
    rp = build_report(wants, as_of, args.tuition_line)
    out = render_report(rp, args.format)
    text, code = out
    print(text)
    return code


def cmd_check(args):
    wants = parse_wants(args.grass)
    validate_wants(wants)
    seeded = parse_date(args.seeded, " (--seeded)")
    today = parse_date(args.today, " (--today)")
    if args.price is not None and args.price < 0:
        raise Refuse("--price must be >= 0")
    ck = build_check(wants, args.item, args.price, args.tag, seeded, today,
                     args.cool)
    out = render_check(ck, args.format)
    text, code = out
    print(text)
    return code


def cmd_doctor(args):
    wants = parse_wants(args.grass)
    validate_wants(wants)
    problems = doctor_problems(wants)
    out = render_doctor(wants, problems, args.format)
    text, code = out
    print(text)
    return code


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="种草账 · Want Ledger — keep a ledger of the wanting, "
                    "not just the buying.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("report", help="desire census: half-life, survival, "
                                      "regret arms, tuition")
    p.add_argument("grass", help="grass CSV (种草日,品名,价位[,标签][,结局,结局日,后悔][,备注])")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="audit date YYYY-MM-DD (default: ledger's last day)")
    p.add_argument("--tuition-line", dest="tuition_line", type=float,
                   default=DEFAULT_TUITION_LINE,
                   help="REGRET-HEAVY line in %% of spending (default %.0f)"
                        % DEFAULT_TUITION_LINE)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("check", help="cooling gate for tonight's sprout")
    p.add_argument("grass", help="grass CSV (种草日,品名,价位[,标签][,结局,结局日,后悔][,备注])")
    p.add_argument("--item", dest="item", required=True, help="品名")
    p.add_argument("--price", dest="price", type=float, default=None,
                   help="your stated price for it")
    p.add_argument("--tag", dest="tag", default="", help="标签")
    p.add_argument("--seeded", dest="seeded", required=True,
                   help="the day you first wanted it YYYY-MM-DD")
    p.add_argument("--today", dest="today", required=True,
                   help="today YYYY-MM-DD (pinned for reproducibility)")
    p.add_argument("--cool", dest="cool", type=float, default=DEFAULT_COOL,
                   help="cooling period in days (default %.0f)" % DEFAULT_COOL)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("doctor", help="data physical exam")
    p.add_argument("grass", help="grass CSV (种草日,品名,价位[,标签][,结局,结局日,后悔][,备注])")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_doctor)
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
