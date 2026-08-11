#!/usr/bin/env python3
"""
decision-debt -- treat postponed decisions as debt that accrues interest.

A decision is neither a task (no clear "done") nor a calendar item (no time).
It is an *open loop* that stays open until you commit. While open it accrues
"decision debt": cognitive interest that grows with its age, with how often you
re-open it, and with how long it has been since you actually looked at it.

This tool keeps a Decision Ledger (JSON) and lets you:
    init      create an empty ledger in this directory
    add       open a new decision
    list      show decisions sorted by debt (hottest first)
    review    surface the top-N hottest open decisions (the pay-down ritual)
    touch     mark a decision as looked-at today (refreshes staleness)
    commit    close a decision with a chosen outcome
    abandon   close a decision without acting on it
    reopen    re-open a previously closed decision (accrues interest faster)
    report    summary: counts, total open debt, hottest decision, aging buckets
    export    render the closed decisions as a markdown decision log (ADR-lite)

Zero third-party dependencies. Python 3.8+.

The debt formula (open decisions only):

    AGE            = (as_of - opened).days
    BASE_INTEREST  = 1 + REOPEN_RATE * reopens
    STALENESS      = 1 + min(SINCE_REVIEW / REVIEW_HORIZON_DAYS, STALENESS_CAP)
    DEBT           = round(weight * AGE * BASE_INTEREST * STALENESS, 1)

where SINCE_REVIEW = (as_of - last_reviewed).days.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

# --- Tunable constants -------------------------------------------------------

LEDGER_DIR = ".decision-debt"
LEDGER_FILE = "ledger.json"
LEDGER_VERSION = 1

DEFAULT_WEIGHT = 3            # importance multiplier, 1..5
REOPEN_RATE = 0.5             # each reopen adds 50% to the interest rate
REVIEW_HORIZON_DAYS = 14      # a decision unreviewed this long hits staleness x2
STALENESS_CAP = 5.0           # maximum extra staleness multiplier (so x6 max)

VALID_STATUS = ("open", "committed", "abandoned")


# --- Data model --------------------------------------------------------------

@dataclass
class Decision:
    id: str
    title: str
    context: str
    options: List[str]
    weight: int
    opened: str            # ISO date
    last_reviewed: str     # ISO date
    reopens: int
    status: str
    outcome: Optional[str]
    closed: Optional[str]  # ISO date when committed/abandoned

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "context": self.context,
            "options": list(self.options),
            "weight": self.weight,
            "opened": self.opened,
            "last_reviewed": self.last_reviewed,
            "reopens": self.reopens,
            "status": self.status,
            "outcome": self.outcome,
            "closed": self.closed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(
            id=d["id"],
            title=d["title"],
            context=d.get("context", ""),
            options=list(d.get("options", [])),
            weight=int(d.get("weight", DEFAULT_WEIGHT)),
            opened=d["opened"],
            last_reviewed=d.get("last_reviewed", d["opened"]),
            reopens=int(d.get("reopens", 0)),
            status=d.get("status", "open"),
            outcome=d.get("outcome"),
            closed=d.get("closed"),
        )


# --- Persistence -------------------------------------------------------------

def ledger_path(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os_getenv()
    if env:
        return Path(env)
    return Path(LEDGER_DIR) / LEDGER_FILE


def os_getenv() -> Optional[str]:
    # tiny indirection so tests can monkeypatch if needed
    import os as _os
    return _os.environ.get("DECISION_LEDGER")


def load_ledger(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no ledger found at {path}. Run `decision-debt init` first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    decisions = [Decision.from_dict(d) for d in data.get("decisions", [])]
    return {"version": data.get("version", LEDGER_VERSION), "decisions": decisions}


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": ledger["version"],
        "decisions": [d.to_dict() for d in ledger["decisions"]],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Scoring -----------------------------------------------------------------

def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def compute_debt(decision: Decision, as_of: date) -> float:
    """Deterministic decision-debt score. Closed decisions always have 0 debt."""
    if decision.status != "open":
        return 0.0
    age = (as_of - _d(decision.opened)).days
    since_review = (as_of - _d(decision.last_reviewed)).days
    base_interest = 1.0 + REOPEN_RATE * decision.reopens
    staleness = 1.0 + min(since_review / REVIEW_HORIZON_DAYS, STALENESS_CAP)
    raw = decision.weight * age * base_interest * staleness
    return round(raw, 1)


def debt_ranking(decisions: List[Decision], as_of: date) -> List[tuple]:
    """Return [(decision, debt)] for open decisions, sorted by debt desc then id."""
    scored = [(d, compute_debt(d, as_of)) for d in decisions if d.status == "open"]
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored


# --- Helpers -----------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "decision"


def _unique_id(base: str, decisions: List[Decision]) -> str:
    existing = {d.id for d in decisions}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def _iso(d: date) -> str:
    return d.isoformat()


def _find(decisions: List[Decision], did: str) -> Decision:
    for d in decisions:
        if d.id == did:
            return d
    raise SystemExit(f"no decision with id {did!r}")


def _fmt_debt(x: float) -> str:
    return f"{x:.1f}"


# --- Commands (each returns a string; main() prints) -------------------------

def cmd_init(path: Path, force: bool = False, **_kw) -> str:
    if path.exists() and not force:
        raise SystemExit(
            f"ledger already exists at {path}. Use --force to reinitialize."
        )
    save_ledger(path, {"version": LEDGER_VERSION, "decisions": []})
    return f"created empty ledger at {path}"


def cmd_add(
    path: Path,
    title: str,
    context: str = "",
    options: Optional[List[str]] = None,
    weight: int = DEFAULT_WEIGHT,
    did: Optional[str] = None,
    as_of: Optional[date] = None,
    **_kw,
) -> str:
    as_of = as_of or date.today()
    if not 1 <= weight <= 5:
        raise SystemExit("--weight must be between 1 and 5")
    ledger = load_ledger(path)
    new_id = did or _unique_id(_slugify(title), ledger["decisions"])
    if any(d.id == new_id for d in ledger["decisions"]):
        raise SystemExit(f"id {new_id!r} already exists; choose another with --id")
    today = _iso(as_of)
    d = Decision(
        id=new_id,
        title=title,
        context=context,
        options=[o for o in (options or []) if o],
        weight=weight,
        opened=today,
        last_reviewed=today,
        reopens=0,
        status="open",
        outcome=None,
        closed=None,
    )
    ledger["decisions"].append(d)
    save_ledger(path, ledger)
    return f"opened decision {new_id!r} (weight {weight}) on {today}"


def cmd_list(
    path: Path,
    status: Optional[str] = None,
    as_of: Optional[date] = None,
    as_json: bool = False,
    **_kw,
) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    decisions = ledger["decisions"]
    if status:
        decisions = [d for d in decisions if d.status == status]
    open_scored = {d.id: debt for d, debt in debt_ranking(decisions, as_of)}
    rows = list(decisions)
    if status == "open" or status is None:
        # open ones sort by debt desc; keep closed ones after, by closed date
        open_rows = [d for d in rows if d.status == "open"]
        closed_rows = [d for d in rows if d.status != "open"]
        open_rows.sort(key=lambda d: (-open_scored.get(d.id, 0.0), d.id))
        closed_rows.sort(key=lambda d: (d.closed or "", d.id))
        rows = open_rows + closed_rows

    if as_json:
        out = []
        for d in rows:
            out.append({
                **d.to_dict(),
                "debt": round(open_scored.get(d.id, 0.0), 1),
            })
        return json.dumps(out, indent=2, ensure_ascii=False)

    if not rows:
        return "no decisions to show."
    lines = [f"{'ID':<24} {'STATUS':<11} {'DEBT':>7}  {'W':>1} {'AGE':>4}  TITLE"]
    lines.append("-" * 78)
    for d in rows:
        debt = open_scored.get(d.id, 0.0) if d.status == "open" else 0.0
        age = (as_of - _d(d.opened)).days
        lines.append(
            f"{d.id:<24} {d.status:<11} {_fmt_debt(debt):>7}  {d.weight} {age:>4}d {d.title}"
        )
    return "\n".join(lines)


def cmd_review(path: Path, top: int = 5, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    scored = debt_ranking(ledger["decisions"], as_of)[:top]
    if not scored:
        return "no open decisions. You are debt-free. Nice."
    total = round(sum(s for _, s in scored), 1)
    lines = [f"Top {len(scored)} hottest decisions (as of {as_of.isoformat()}):"]
    lines.append("")
    for i, (d, debt) in enumerate(scored, 1):
        since = (as_of - _d(d.last_reviewed)).days
        lines.append(
            f"  {i}. [{_fmt_debt(debt)}] {d.id}  --  {d.title}\n"
            f"     weight {d.weight} | age {(as_of - _d(d.opened)).days}d | "
            f"unreviewed {since}d | reopens {d.reopens}"
        )
    lines.append("")
    lines.append("Pay-down ritual:")
    lines.append("  For each: `touch <id>` once considered, then `commit <id>` or `abandon <id>`.")
    lines.append(f"  Combined open debt in this view: {total}")
    return "\n".join(lines)


def cmd_touch(path: Path, did: str, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    d = _find(ledger["decisions"], did)
    if d.status != "open":
        raise SystemExit(f"{did} is not open (status={d.status}); touch only open decisions")
    d.last_reviewed = _iso(as_of)
    save_ledger(path, ledger)
    return f"refreshed {did}: last_reviewed -> {d.last_reviewed} (staleness reset)"


def cmd_commit(
    path: Path, did: str, outcome: str, as_of: Optional[date] = None, **_kw
) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    d = _find(ledger["decisions"], did)
    d.status = "committed"
    d.outcome = outcome
    d.closed = _iso(as_of)
    save_ledger(path, ledger)
    return f"committed {did} on {d.closed}: {outcome}"


def cmd_abandon(path: Path, did: str, reason: str, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    d = _find(ledger["decisions"], did)
    d.status = "abandoned"
    d.outcome = reason
    d.closed = _iso(as_of)
    save_ledger(path, ledger)
    return f"abandoned {did} on {d.closed}: {reason}"


def cmd_reopen(path: Path, did: str, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    d = _find(ledger["decisions"], did)
    if d.status == "open":
        raise SystemExit(f"{did} is already open")
    d.status = "open"
    d.outcome = None
    d.closed = None
    d.reopens += 1
    d.last_reviewed = _iso(as_of)
    save_ledger(path, ledger)
    return (f"reopened {did} (reopens={d.reopens}). "
            f"Note: each reopen raises its interest rate by {int(REOPEN_RATE * 100)}%.")


def cmd_report(path: Path, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    decisions = ledger["decisions"]
    counts = {s: 0 for s in VALID_STATUS}
    for d in decisions:
        counts[d.status] = counts.get(d.status, 0) + 1
    scored = debt_ranking(decisions, as_of)
    total_debt = round(sum(s for _, s in scored), 1)
    # aging buckets for open decisions
    buckets = {"0-7d": 0, "8-30d": 0, "31-90d": 0, "90d+": 0}
    for d, _ in scored:
        age = (as_of - _d(d.opened)).days
        if age <= 7:
            buckets["0-7d"] += 1
        elif age <= 30:
            buckets["8-30d"] += 1
        elif age <= 90:
            buckets["31-90d"] += 1
        else:
            buckets["90d+"] += 1

    lines = [f"Decision Debt Report  (as of {as_of.isoformat()})"]
    lines.append("=" * 48)
    lines.append("")
    lines.append("Inventory:")
    lines.append(f"  open        : {counts.get('open', 0)}")
    lines.append(f"  committed   : {counts.get('committed', 0)}")
    lines.append(f"  abandoned   : {counts.get('abandoned', 0)}")
    lines.append(f"  total       : {len(decisions)}")
    lines.append("")
    lines.append(f"Total open debt: {total_debt}")
    if scored:
        top_d, top_s = scored[0]
        lines.append(f"Hottest: {top_d.id} = {_fmt_debt(top_s)}  ({top_d.title})")
    else:
        lines.append("Hottest: <none> -- no open decisions")
    lines.append("")
    lines.append("Open decisions by age:")
    for k in ("0-7d", "8-30d", "31-90d", "90d+"):
        lines.append(f"  {k:<7}: {buckets[k]}")
    return "\n".join(lines)


def cmd_export(path: Path, as_of: Optional[date] = None, **_kw) -> str:
    as_of = as_of or date.today()
    ledger = load_ledger(path)
    decisions = ledger["decisions"]
    committed = [d for d in decisions if d.status == "committed"]
    abandoned = [d for d in decisions if d.status == "abandoned"]
    committed.sort(key=lambda d: (d.closed or "", d.id))
    abandoned.sort(key=lambda d: (d.closed or "", d.id))

    lines = ["# Decision Log", ""]
    lines.append("A lightweight ADR-style record of decisions closed with `decision-debt`.")
    lines.append("")
    lines.append("## Committed")
    lines.append("")
    if not committed:
        lines.append("_None yet._")
    for d in committed:
        lines.append(f"### {d.id} -- {d.title}")
        lines.append("")
        lines.append(f"- **Decided:** {d.closed}")
        lines.append(f"- **Opened:** {d.opened}")
        days = (_d(d.closed) - _d(d.opened)).days if d.closed else 0
        lines.append(f"- **Days open:** {days}")
        lines.append(f"- **Weight:** {d.weight}")
        if d.options:
            lines.append(f"- **Options considered:** {', '.join(d.options)}")
        if d.context:
            lines.append(f"- **Context:** {d.context}")
        lines.append(f"- **Outcome:** {d.outcome}")
        lines.append("")
    lines.append("## Abandoned")
    lines.append("")
    if not abandoned:
        lines.append("_None._")
    for d in abandoned:
        lines.append(f"- **{d.id}** ({d.closed}) -- {d.title}: {d.outcome}")
    lines.append("")
    return "\n".join(lines)


# --- Argument parsing --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="decision-debt",
        description="Treat postponed decisions as debt that accrues interest.",
    )
    p.add_argument("--ledger", default=None, help=f"path to ledger JSON (default: {LEDGER_DIR}/{LEDGER_FILE})")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create an empty ledger")
    sp.add_argument("--force", action="store_true", help="reinitialize even if a ledger exists")

    sp = sub.add_parser("add", help="open a new decision")
    sp.add_argument("--title", required=True)
    sp.add_argument("--context", default="")
    sp.add_argument("--option", action="append", default=[], help="a candidate option (repeatable)")
    sp.add_argument("--weight", type=int, default=DEFAULT_WEIGHT, help="importance 1..5 (default 3)")
    sp.add_argument("--id", dest="did", default=None, help="explicit id (default: slug of title)")

    sp = sub.add_parser("list", help="list decisions")
    sp.add_argument("--status", choices=list(VALID_STATUS), default=None)
    sp.add_argument("--json", action="store_true", help="emit JSON")

    sp = sub.add_parser("review", help="show the hottest open decisions")
    sp.add_argument("--top", type=int, default=5)

    sp = sub.add_parser("touch", help="refresh a decision's last_reviewed to today")
    sp.add_argument("did", metavar="id")

    sp = sub.add_parser("commit", help="close a decision with an outcome")
    sp.add_argument("did", metavar="id")
    sp.add_argument("--outcome", required=True, help="what you decided")

    sp = sub.add_parser("abandon", help="close a decision without acting")
    sp.add_argument("did", metavar="id")
    sp.add_argument("--reason", required=True, help="why it is abandoned")

    sp = sub.add_parser("reopen", help="re-open a closed decision")
    sp.add_argument("did", metavar="id")

    sp = sub.add_parser("report", help="summary report")

    sp = sub.add_parser("export", help="render closed decisions as markdown")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    path = ledger_path(args.ledger)
    fn = {
        "init": cmd_init,
        "add": cmd_add,
        "list": cmd_list,
        "review": cmd_review,
        "touch": cmd_touch,
        "commit": cmd_commit,
        "abandon": cmd_abandon,
        "reopen": cmd_reopen,
        "report": cmd_report,
        "export": cmd_export,
    }[args.command]

    kw = vars(args).copy()
    kw.pop("command")
    kw.pop("ledger", None)
    out = fn(path, **kw)
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
