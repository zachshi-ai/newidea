#!/usr/bin/env python3
"""求职漏斗 · Job Funnel.

A conversion ledger for the job hunt. Rejections are mostly silent, and
the brain reads every silence as a verdict on you. This tool keeps one
row per application and turns the pile into a measurable funnel:

  * funnel   - stage-by-stage conversion (applied -> response -> interview
               -> offer), each rate carrying a Wilson lower bound so that
               0/12 and 0/40 are never mistaken for the same zero; the
               weakest *provable* stage is the leak.
  * channels - per-channel conversion ranked by the same lower bound, so
               the champion is the one that has proven itself, not the one
               that got lucky twice; effort-vs-proof mismatch is called out.
  * aging    - pending applications against your personal silence deadline
               (the P90 of your own response latencies); past the line an
               application is statistically dead and may be closed.
  * show     - one application's full timeline and its channel snapshot.

Zero dependency: Python 3.8+ standard library only. Everything stays local.
"""

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import OrderedDict
from datetime import date

PROG = "job_funnel.py"

# Wilson lower-bound z for ~95% one-sided confidence.
Z = 1.96
# A stage/channel rate with fewer than this many chances is tagged THIN:
# its rate is a rumor, not a rate.
DEFAULT_MIN_N = 10
# Silence deadline fallback when fewer than this many applications have a
# known reply date (borrowed default, labeled as such in the report).
DEFAULT_DEADLINE = 21
MIN_LATENCY_SAMPLES = 5
P90 = 0.9

# outcome vocabulary: how far down the funnel an application reached.
# Empty means pending. "withdrawn" is excluded from funnel denominators
# (you ended it, the funnel did not).
OUTCOME_ALIASES = {
    "": "pending", "pending": "pending", "waiting": "pending",
    "待定": "pending", "等待": "pending", "无": "pending",
    "rejected": "rejected", "reject": "rejected", "no": "rejected",
    "拒": "rejected", "拒绝": "rejected", "挂了": "rejected",
    "response": "response", "screen": "response", "replied": "response",
    "回复": "response", "沟通": "response",
    "interview": "interview", "面试": "interview",
    "offer": "offer", "录用": "offer", "录取": "offer", "聘书": "offer",
    "withdrawn": "withdrawn", "withdraw": "withdrawn", "closed": "withdrawn",
    "撤回": "withdrawn", "放弃": "withdrawn", "关闭": "withdrawn",
}
DECIDED = ("rejected", "response", "interview", "offer")
REACHED_RESPONSE = ("response", "interview", "offer")
REACHED_INTERVIEW = ("interview", "offer")

APPLIED_ALIASES = {"applied", "date", "application_date", "投递日", "申请日",
                   "投递日期"}
COMPANY_ALIASES = {"company", "employer", "公司"}
ROLE_ALIASES = {"role", "position", "job", "职位", "岗位"}
CHANNEL_ALIASES = {"channel", "source", "渠道", "来源"}
OUTCOME_HEADERS = {"outcome", "status", "state", "result", "结果", "状态"}
REPLIED_ALIASES = {"replied", "reply_date", "response_date", "回复日",
                   "回复日期", "响应日"}

ENDPOINTS = OrderedDict([
    ("response", REACHED_RESPONSE),
    ("interview", REACHED_INTERVIEW),
    ("offer", ("offer",)),
])


class ParseError(Exception):
    """Ledger cannot be parsed; message is user-facing."""


def plural(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def redact(text):
    return "anon-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def parse_date(text):
    s = str(text).strip()
    normalized = s.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace(".", "-").replace("/", "-").strip("-")
    parts = [p for p in normalized.split("-") if p != ""]
    if len(parts) == 3:
        try:
            return date(*(int(p) for p in parts))
        except ValueError:
            pass
    if len(parts) == 1 and len(parts[0]) == 8 and parts[0].isdigit():
        try:
            return date(int(parts[0][:4]), int(parts[0][4:6]), int(parts[0][6:8]))
        except ValueError:
            pass
    raise ParseError("unrecognized date: %r" % text)


def _clean_header(cell):
    return str(cell or "").strip().lstrip("\ufeff").strip().lower()


def _find_header(rows):
    best = None
    for idx, cells in enumerate(rows[:50]):
        lowered = [_clean_header(c) for c in cells]
        ai = ci = ri = hi = oi = pi = None
        for i, h in enumerate(lowered):
            if ai is None and h in APPLIED_ALIASES:
                ai = i
            elif ci is None and h in COMPANY_ALIASES:
                ci = i
            elif hi is None and h in CHANNEL_ALIASES:
                hi = i
            elif ri is None and h in ROLE_ALIASES:
                ri = i
            elif oi is None and h in OUTCOME_HEADERS:
                oi = i
            elif pi is None and h in REPLIED_ALIASES:
                pi = i
        if ai is not None and ci is not None and hi is not None:
            best = (idx, ai, ci, ri, hi, oi, pi)
            break
    if best is None:
        raise ParseError(
            "no header row found: need applied (%s), company (%s) and "
            "channel (%s) columns; role (%s), outcome (%s) and replied (%s) "
            "are optional" % (
                "/".join(sorted(APPLIED_ALIASES)[:3]),
                "/".join(sorted(COMPANY_ALIASES)[:2]),
                "/".join(sorted(CHANNEL_ALIASES)[:2]),
                "/".join(sorted(ROLE_ALIASES)[:2]),
                "/".join(sorted(OUTCOME_HEADERS)[:2]),
                "/".join(sorted(REPLIED_ALIASES)[:2])))
    return best


def read_ledger(path):
    """Parse the applications ledger CSV into a list of row dicts."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            raw = list(csv.reader(fh))
    except OSError as exc:
        raise ParseError("cannot read %s: %s" % (path, exc))
    except UnicodeDecodeError:
        raise ParseError("%s is not valid UTF-8" % path)

    rows = [r for r in raw if any(str(c).strip() for c in r)]
    if not rows:
        raise ParseError("%s: no data rows" % path)

    header_idx, ai, ci, ri, hi, oi, pi = _find_header(rows)
    ledger = []
    for lineno, cells in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        def cell(i):
            return cells[i].strip() if i is not None and i < len(cells) else ""
        try:
            applied = parse_date(cell(ai))
        except ParseError as exc:
            raise ParseError("%s line %d: %s" % (path, lineno, exc))
        company = cell(ci)
        channel = cell(hi)
        if not company:
            raise ParseError("%s line %d: company is empty" % (path, lineno))
        if not channel:
            raise ParseError("%s line %d: channel is empty" % (path, lineno))
        outcome_text = cell(oi).lower()
        if outcome_text not in OUTCOME_ALIASES:
            raise ParseError(
                "%s line %d: unknown outcome %r (use pending/rejected/"
                "response/interview/offer/withdrawn)" % (path, lineno, cell(oi)))
        replied_text = cell(pi)
        replied = None
        if replied_text:
            try:
                replied = parse_date(replied_text)
            except ParseError as exc:
                raise ParseError("%s line %d: %s" % (path, lineno, exc))
            if replied < applied:
                raise ParseError(
                    "%s line %d: replied %s before applied %s" % (
                        path, lineno, replied.isoformat(), applied.isoformat()))
        ledger.append({
            "company": company, "role": cell(ri), "channel": channel,
            "applied": applied,
            "outcome": OUTCOME_ALIASES[outcome_text],
            "replied": replied,
            "line": lineno,
        })
    if not ledger:
        raise ParseError("%s: header found but no data rows" % path)
    return ledger


# ---------------------------------------------------------------------------
# the honest math
# ---------------------------------------------------------------------------

def wilson_lb(k, n, z=Z):
    """Lower bound of the Wilson score interval for k successes in n trials.

    A raw rate from a small sample lies by omission: 2/3 "feels" better
    than 20/100, but its lower bound is far worse. Ranking by the lower
    bound is the honest way to compare channels and stages.
    """
    if n <= 0:
        return 0.0
    p = k / float(n)
    z2 = z * z
    denom = 1 + z2 / n
    center = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, (center - margin) / denom)


def percentile_nearest_rank(sorted_values, q):
    if not sorted_values:
        raise ValueError("no values")
    rank = max(1, int(math.ceil(q * len(sorted_values))))
    return sorted_values[rank - 1]


def silence_deadline(ledger, default_deadline=DEFAULT_DEADLINE):
    """Your personal silence line: the P90 of known first-reply latencies.

    Below the minimum sample it falls back to a borrowed default, labeled
    as such — a deadline you did not mine is still a deadline, but the
    report must say where it came from.
    """
    latencies = sorted((r["replied"] - r["applied"]).days
                       for r in ledger if r["replied"])
    if len(latencies) >= MIN_LATENCY_SAMPLES:
        return percentile_nearest_rank(latencies, P90), len(latencies), False
    return default_deadline, len(latencies), True


def funnel_report(ledger, min_n=DEFAULT_MIN_N):
    decided = [r for r in ledger if r["outcome"] in DECIDED]
    n_applied = len(decided)
    n_response = sum(1 for r in decided if r["outcome"] in REACHED_RESPONSE)
    n_interview = sum(1 for r in decided if r["outcome"] in REACHED_INTERVIEW)
    n_offer = sum(1 for r in decided if r["outcome"] == "offer")
    stages = []
    for src, dst, n, k in (
            ("applied", "response", n_applied, n_response),
            ("response", "interview", n_response, n_interview),
            ("interview", "offer", n_interview, n_offer)):
        stages.append({
            "from": src, "to": dst, "n": n, "passes": k,
            "rate": (k / float(n)) if n else 0.0,
            "lb": wilson_lb(k, n),
            "thin": n < min_n,
        })
    proven = [s for s in stages if not s["thin"]]
    leak = min(proven, key=lambda s: s["lb"]) if proven else None
    return {
        "total": len(ledger),
        "decided": n_applied,
        "pending": sum(1 for r in ledger if r["outcome"] == "pending"),
        "withdrawn": sum(1 for r in ledger if r["outcome"] == "withdrawn"),
        "offers": n_offer,
        "stages": stages,
        "leak": leak,
        "starving": not proven,
        "min_n": min_n,
    }


def channels_report(ledger, endpoint="response", min_n=DEFAULT_MIN_N):
    reached = ENDPOINTS[endpoint]
    grouped = OrderedDict()
    for r in ledger:
        grouped.setdefault(r["channel"].strip().lower(), []).append(r)
    rows = []
    for name, rows_in in grouped.items():
        n = len(rows_in)
        k = sum(1 for r in rows_in if r["outcome"] in reached)
        rows.append({
            "channel": rows_in[0]["channel"],  # original spelling
            "n": n,
            "success": k,
            "pending": sum(1 for r in rows_in if r["outcome"] == "pending"),
            "rate": k / float(n) if n else 0.0,
            "lb": wilson_lb(k, n),
            "thin": n < min_n,
        })
    rows.sort(key=lambda r: (-r["lb"], -r["rate"], r["channel"].lower()))
    proven = [r for r in rows if not r["thin"]]
    proven_best = proven[0] if proven else None
    effort_champ = None
    if rows:
        effort_champ = max(rows, key=lambda r: r["n"])
        ties = [r for r in rows if r["n"] == effort_champ["n"]]
        if len(ties) > 1:
            effort_champ = min(ties, key=lambda r: r["channel"].lower())
    return {
        "endpoint": endpoint, "rows": rows, "min_n": min_n,
        "proven_best": proven_best, "effort_champ": effort_champ,
        "total": len(ledger),
    }


def aging_report(ledger, as_of, default_deadline=DEFAULT_DEADLINE):
    deadline, samples, borrowed = silence_deadline(ledger, default_deadline)
    pending = [r for r in ledger if r["outcome"] == "pending"]
    rows = []
    for r in pending:
        age = (as_of - r["applied"]).days
        rows.append({
            "row": r, "age": age, "expired": age > deadline,
        })
    rows.sort(key=lambda x: (-x["age"], x["row"]["company"].lower(),
                             x["row"]["role"].lower()))
    expired = [x for x in rows if x["expired"]]
    report = {
        "deadline": deadline, "samples": samples, "borrowed": borrowed,
        "rows": rows, "pending": len(rows), "expired": len(expired),
        "alive": len(rows) - len(expired),
    }
    base = funnel_report(ledger)
    if base["decided"]:
        report["rate_before"] = base["stages"][0]["rate"]
        report["rate_after"] = base["stages"][0]["passes"] / float(
            base["decided"] + len(expired))
    else:
        report["rate_before"] = report["rate_after"] = None
    return report


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def pct(x):
    return "%.1f%%" % (100 * x)


def days_label(n):
    return "%+dd" % n if n < 0 else "%dd" % n


def label_of(row, args):
    company = row["company"]
    if getattr(args, "redact", False):
        company = redact(company)
    return company


def render_funnel_text(report, ledger, args):
    out = []
    out.append("-- Job Funnel: applications-to-offer ledger (as of %s)" % (
        args_as_of(report)))
    out.append("  ledger     : %s · %s decided · %s pending · %s withdrawn · "
               "%s" % (plural(report["total"], "application"),
                       report["decided"], report["pending"],
                       report["withdrawn"],
                       plural(report["offers"], "offer")))
    out.append("  funnel     : decided applications only — pending ones are "
               "not in the denominator yet (see the aging command)")
    out.append("")
    out.append("  %-22s %5s %7s %8s %11s" % ("stage", "n", "passes", "rate",
                                             "wilson lo"))
    for s in report["stages"]:
        name = "%s -> %s" % (s["from"], s["to"])
        mark = ""
        if report["leak"] is s:
            mark = "   <- weakest proven stage"
        elif s["thin"]:
            mark = "  (thin)"
        out.append("  %-22s %5d %7d %8s %11s%s" % (
            name, s["n"], s["passes"], pct(s["rate"]), pct(s["lb"]), mark))
    out.append("")
    if report["starving"]:
        out.append("  sample starvation : every stage is below min-n=%d — no "
                   "stage verdict is provable yet;" % report["min_n"])
        out.append("                      add applications before optimizing "
                   "anything")
    else:
        leak = report["leak"]
        out.append("  weakest proven stage : %s -> %s (wilson lo %s)" % (
            leak["from"], leak["to"], pct(leak["lb"])))
        for line in STAGE_WALLS["%s -> %s" % (leak["from"], leak["to"])]:
            out.append("                         %s" % line)
    thin = [s for s in report["stages"] if s["thin"]]
    if thin:
        names = ", ".join("%s -> %s (n=%d < %d)" % (s["from"], s["to"], s["n"],
                                                    report["min_n"])
                          for s in thin)
        out.append("  thin stages      : %s — with this few samples the rate "
                   "is a rumor, not a rate" % names)
    if report["pending"]:
        out.append("  pending          : %s waiting — closing the dead ones "
                   "will change this funnel" % report["pending"])
    return "\n".join(out)


def args_as_of(report):
    return report["as_of"].isoformat()


STAGE_WALLS = {
    "applied -> response": [
        "the wall is up front: resumes are not turning into conversations —",
        "interview polish cannot fix a funnel that leaks before anyone answers.",
    ],
    "response -> interview": [
        "interest arrives but stalls before the room — screening is filtering",
        "you out; sharpen the stories, not the application volume.",
    ],
    "interview -> offer": [
        "you reach the room but not the signature — closing is the leak,",
        "and it is also the most practiceable stage of the three.",
    ],
}


def render_channels_text(report, args):
    out = []
    out.append("-- Job Funnel channels: endpoint = %s (as of %s)" % (
        report["endpoint"], args_as_of(report)))
    out.append("  %-16s %5s %8s %8s %8s %11s" % (
        "channel", "n", "success", "pending", "rate", "wilson lo"))
    for r in report["rows"]:
        mark = ""
        if report["proven_best"] is r:
            mark = "   <- proven best"
        elif r["thin"]:
            mark = "  (thin)"
        out.append("  %-16s %5d %8d %8d %8s %11s%s" % (
            r["channel"][:16], r["n"], r["success"], r["pending"],
            pct(r["rate"]), pct(r["lb"]), mark))
    out.append("")
    champ = report["effort_champ"]
    best = report["proven_best"]
    if champ is not None:
        share = 100.0 * champ["n"] / report["total"] if report["total"] else 0
        out.append("  effort champion : %s — %s of %s applications (%.0f%%)" % (
            champ["channel"], champ["n"], report["total"], share))
    if best is None:
        out.append("  proven champion : none yet — no channel has min-n=%d "
                   "applications, volume proves nothing so far"
                   % report["min_n"])
    elif champ is not None and best["channel"].lower() == champ["channel"].lower():
        out.append("  champions aligned: most effort and best proof agree on "
                   "%s — keep feeding it" % best["channel"])
    elif champ is not None:
        out.append("  proven champion : %s — wilson lo %s vs the incumbent's %s"
                   % (best["channel"], pct(best["lb"]), pct(champ["lb"])))
        if champ["lb"] > 0:
            ratio = best["lb"] / champ["lb"]
            out.append("  mismatch        : %s carries the volume while %s "
                           "outperforms it ~%s — correlation is not cause"
                           % (champ["channel"], best["channel"],
                              human_ratio(ratio)))
            out.append("                    (referrals arrive pre-vetted), "
                       "but the budget is upside-down")
        else:
            out.append("  mismatch        : %s carries the volume while %s "
                       "proves itself — the incumbent's" % (
                           champ["channel"], best["channel"]))
            out.append("                    lower bound is zero: the volume "
                       "is going to the least proven channel")
    return "\n".join(out)


def human_ratio(x):
    if x >= 10:
        return "%dx" % round(x)
    return "%.1fx" % x


def render_aging_text(report, args):
    out = []
    origin = ("P90 of %s answered" % plural(report["samples"], "application")
              if not report["borrowed"] else
              "borrowed default — only %s answered application(s) on record"
              % report["samples"])
    out.append("-- Job Funnel aging: pending applications (as of %s)" % (
        args_as_of(report)))
    out.append("  silence deadline : %dd (%s)" % (report["deadline"], origin))
    out.append("  pending          : %s · %s expired beyond the line · %s "
               "still alive" % (plural(report["pending"], "application"),
                                report["expired"], report["alive"]))
    out.append("")
    out.append("  %-20s %-28s %-10s %-10s %6s  verdict" % (
        "company", "role", "channel", "applied", "age"))
    for x in report["rows"][:getattr(args, "top", 15)]:
        r = x["row"]
        verdict = ("EXPIRED — silent past the line; statistically already dead"
                   if x["expired"] else "alive")
        out.append("  %-20s %-28s %-10s %-10s %6s  %s" % (
            label_of(r, args)[:20], r["role"][:28], r["channel"][:10],
            r["applied"].isoformat(), days_label(x["age"]), verdict))
    shown = min(len(report["rows"]), getattr(args, "top", 15))
    if len(report["rows"]) > shown:
        out.append("  … and %d more" % (len(report["rows"]) - shown))
    out.append("")
    if report["expired"] and report["rate_before"] is not None:
        out.append("  %d pending are past your silence line — close them and "
                   "the honest response rate" % report["expired"])
        out.append("  reads %s -> %s. A ledger that never buries anything "
                   "measures nothing." % (pct(report["rate_before"]),
                                          pct(report["rate_after"])))
    if report["expired"]:
        out.append("  gate: ACTION — close the dead, keep the alive waiting")
    else:
        out.append("  gate: CLEAR — every pending application is still inside "
                   "the silence window")
    return "\n".join(out)


def render_show_text(row, chan, as_of, deadline, args):
    out = []
    out.append("-- Job Funnel: %s · %s" % (label_of(row, args),
                                           row["role"] or "(no role)"))
    out.append("  applied %s via %s" % (row["applied"].isoformat(),
                                        row["channel"]))
    if row["replied"]:
        lat = (row["replied"] - row["applied"]).days
        out.append("  first reply %s (%dd — your silence line is %dd)" % (
            row["replied"].isoformat(), lat, deadline))
    verdict = {
        "pending": "pending — still inside the waiting room",
        "rejected": "rejected — the funnel closed here",
        "response": "reached a conversation, stalled before the interview",
        "interview": "reached the interview, no offer (yet)",
        "offer": "offer — the whole point of the funnel",
        "withdrawn": "withdrawn — you ended it, not the funnel",
    }[row["outcome"]]
    out.append("  outcome  : %s" % verdict)
    if chan:
        out.append("  channel  : %s · %s, %s response (wilson lo %s)%s" % (
            chan["channel"], plural(chan["n"], "application"),
            pct(chan["rate"]), pct(chan["lb"]),
            " (thin)" if chan["thin"] else ""))
    if row["outcome"] == "pending":
        age = (as_of - row["applied"]).days
        state = ("EXPIRED — %s past the line, statistically already dead"
                 % days_label(age - deadline)) if age > deadline else \
                "alive — %s inside the line" % days_label(deadline - age)
        out.append("  waiting  : %s on the clock — %s" % (days_label(age),
                                                          state))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def stage_json(s):
    return {"from": s["from"], "to": s["to"], "n": s["n"],
            "passes": s["passes"], "rate": round(s["rate"], 4),
            "wilson_lb": round(s["lb"], 4), "thin": s["thin"]}


def channel_json(r, args):
    return {"channel": label_of(r, args) if getattr(args, "redact", False)
            else r["channel"], "n": r["n"], "success": r["success"],
            "pending": r["pending"], "rate": round(r["rate"], 4),
            "wilson_lb": round(r["lb"], 4), "thin": r["thin"]}


def render_funnel_json(report, args):
    payload = {
        "total": report["total"], "decided": report["decided"],
        "pending": report["pending"], "withdrawn": report["withdrawn"],
        "offers": report["offers"], "min_n": report["min_n"],
        "stages": [stage_json(s) for s in report["stages"]],
        "leak": stage_json(report["leak"]) if report["leak"] else None,
        "starving": report["starving"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_channels_json(report, args):
    payload = {
        "endpoint": report["endpoint"], "min_n": report["min_n"],
        "total": report["total"],
        "channels": [channel_json(r, args) for r in report["rows"]],
        "effort_champion": (channel_json(report["effort_champ"], args)
                            if report["effort_champ"] else None),
        "proven_champion": (channel_json(report["proven_best"], args)
                            if report["proven_best"] else None),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_aging_json(report, args):
    payload = {
        "deadline_days": report["deadline"], "samples": report["samples"],
        "borrowed_default": report["borrowed"],
        "pending": report["pending"], "expired": report["expired"],
        "alive": report["alive"],
        "response_rate_if_closed": {
            "before": round(report["rate_before"], 4)
            if report["rate_before"] is not None else None,
            "after": round(report["rate_after"], 4)
            if report["rate_after"] is not None else None,
        },
        "applications": [{
            "company": label_of(x["row"], args), "role": x["row"]["role"],
            "channel": x["row"]["channel"],
            "applied": x["row"]["applied"].isoformat(),
            "age_days": x["age"], "expired": x["expired"],
        } for x in report["rows"]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_show_json(row, chan, args):
    payload = {
        "company": label_of(row, args), "role": row["role"],
        "channel": row["channel"], "applied": row["applied"].isoformat(),
        "outcome": row["outcome"],
        "replied": row["replied"].isoformat() if row["replied"] else None,
    }
    if chan:
        payload["channel_stats"] = channel_json(chan, args)
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_as_of(text):
    try:
        return parse_date(text)
    except ParseError:
        raise ParseError("--as-of must be a date (YYYY-MM-DD), got %r" % text)


def build_parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="A conversion ledger for the job hunt: funnel stages, "
                    "honest channel rankings, and a personal silence line "
                    "(zero dependency, fully local).")
    sub = p.add_subparsers(dest="cmd")

    def common(pa):
        pa.add_argument("ledger", help="applications ledger CSV "
                        "(applied/company/channel[/role/outcome/replied])")
        pa.add_argument("--as-of", default=None, metavar="DATE",
                        help="reference date (default: today)")
        pa.add_argument("--redact", action="store_true",
                        help="hash company names in the report")

    pf = sub.add_parser("funnel", help="stage-by-stage conversion rates and "
                                       "the weakest proven stage")
    common(pf)
    pf.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, metavar="N",
                    help="stages with fewer chances are THIN (default %d)"
                         % DEFAULT_MIN_N)
    pf.add_argument("--format", choices=("text", "json"), default="text")

    pc = sub.add_parser("channels", help="per-channel conversion ranked by "
                                         "Wilson lower bound")
    common(pc)
    pc.add_argument("--endpoint", choices=tuple(ENDPOINTS), default="response",
                    help="what counts as success (default: response)")
    pc.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, metavar="N")
    pc.add_argument("--top", type=int, default=15, metavar="N")
    pc.add_argument("--format", choices=("text", "json"), default="text")

    pa_ = sub.add_parser("aging", help="pending applications vs your personal "
                                       "silence deadline (exit 4 if any "
                                       "expired)")
    common(pa_)
    pa_.add_argument("--default-deadline", type=int,
                     default=DEFAULT_DEADLINE, metavar="DAYS",
                     help="fallback deadline when too few replied rows exist "
                          "(default %dd)" % DEFAULT_DEADLINE)
    pa_.add_argument("--top", type=int, default=15, metavar="N")
    pa_.add_argument("--format", choices=("text", "json"), default="text")

    ps = sub.add_parser("show", help="one application's timeline and its "
                                     "channel snapshot")
    common(ps)
    ps.add_argument("query", help="company (exact) or unique substring of "
                                  "\"company role\"")
    ps.add_argument("--endpoint", choices=tuple(ENDPOINTS), default="response")
    ps.add_argument("--default-deadline", type=int,
                    default=DEFAULT_DEADLINE, metavar="DAYS")
    ps.add_argument("--format", choices=("text", "json"), default="text")
    return p


def find_rows(ledger, query):
    q = query.strip().lower()
    exact = [r for r in ledger if r["company"].strip().lower() == q]
    if len(exact) == 1:
        return exact
    hits = [r for r in ledger
            if q and q in ("%s %s" % (r["company"], r["role"])).lower()]
    if len(hits) == 1:
        return hits
    return exact or hits


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd not in ("funnel", "channels", "aging", "show"):
        parser.print_usage(sys.stderr)
        return 2
    try:
        as_of = parse_as_of(args.as_of) if args.as_of else date.today()
        ledger = read_ledger(args.ledger)

        if args.cmd == "funnel":
            report = funnel_report(ledger, args.min_n)
            report["as_of"] = as_of
            print(render_funnel_json(report, args) if args.format == "json"
                  else render_funnel_text(report, ledger, args))
            return 0

        if args.cmd == "channels":
            report = channels_report(ledger, args.endpoint, args.min_n)
            report["as_of"] = as_of
            print(render_channels_json(report, args) if args.format == "json"
                  else render_channels_text(report, args))
            return 0

        if args.cmd == "aging":
            report = aging_report(ledger, as_of, args.default_deadline)
            report["as_of"] = as_of
            print(render_aging_json(report, args) if args.format == "json"
                  else render_aging_text(report, args))
            return 4 if report["expired"] else 0

        hits = find_rows(ledger, args.query)
        if not hits:
            sys.stderr.write("error: no application matches %r\n" % args.query)
            return 3
        if len(hits) > 1:
            def label(r):
                return "%s · %s" % (r["company"], r["role"] or "(no role)")
            sys.stderr.write("error: %r is ambiguous: %s\n" % (
                args.query, ", ".join(sorted(label(r) for r in hits))))
            return 3
        chans = channels_report(ledger, args.endpoint)
        row = hits[0]
        chan = None
        for c in chans["rows"]:
            if c["channel"].lower() == row["channel"].strip().lower():
                chan = c
                break
        if args.format == "json":
            print(render_show_json(row, chan, args))
        else:
            deadline = silence_deadline(ledger, args.default_deadline)[0]
            print(render_show_text(row, chan, as_of, deadline, args))
        return 0
    except ParseError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 3


if __name__ == "__main__":
    sys.exit(main())
