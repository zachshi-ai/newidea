#!/usr/bin/env python3
"""
Generate deterministic example artifacts for todo-rot.

Builds a real temporary git repo whose history is engineered to hit every
promise-economics case (every date pinned, so commit hashes and every
number are reproducible on any machine):

    2024-01-10  alice   billing.py opens with a FIXME (race on refund)
                        and a TODO (extract validation)
    2024-01-20  alice   adds HACK (cache prices) + legacy.py with a TODO
    2024-03-01  bob     PAYS the validation TODO       -> lifetime  51d
    2025-03-01  alice   adds TODO(alice): add metrics #42
    2025-05-01  chen    git mv billing.py src/billing.py (ages preserved)
    2025-06-01  bob     PAYS the HACK (someone else pays alice's debt)
                        -> lifetime 498d; adds TODO: migrate off sqlite
    2026-08-01  chen    deletes legacy.py (its TODO DIES with the file),
                        adds flags.py with XXX temp flag

Half-life of paid promises = median(51, 498) = 274.5 days, zombie
threshold = 549 days. Of 4 outstanding promises only the 951-day-old
FIXME is a zombie; the 443-day sqlite TODO is ANCIENT but not zombie —
the distinction the tool exists to make.

Then runs the real CLI (as_of pinned to 2026-08-18) and writes:

    examples/sample-ledger.txt
    examples/sample-halflife.txt

and syncs the demo working tree into examples/demo-repo/.  Every
important number is re-asserted from JSON output at the end — the script
fails loudly if metrics drift, so the samples can never silently rot.

Run:   python3 examples/build_examples.py          (rebuild + write)
       python3 examples/build_examples.py --check  (verify, write nothing)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EX = ROOT / "examples"
DEMO = EX / "demo-repo"
AS_OF = "2026-08-18"                    # pinned so reports never change

CLI = sys.executable, str(ROOT / "todo_rot.py")

ALICE = ("Alice Chen", "alice@corp.dev")
BOB = ("Bob Lin", "bob@corp.dev")
CHEN = ("Chen Wu", "chen@corp.dev")


# --- fixture ---------------------------------------------------------------

BILLING_V1 = """\
# FIXME: race condition on refund
# TODO: extract validation
def charge(order):
    return order.total
"""

BILLING_V2 = """\
# FIXME: race condition on refund
# TODO: extract validation
def charge(order):
    return order.total

# HACK: cache prices for 5 minutes
def prices(sku):
    return CACHE[sku]
"""

BILLING_V3 = BILLING_V2.replace("# TODO: extract validation\n", "")

BILLING_V4 = BILLING_V3 + """
# TODO(alice): add metrics #42
"""

BILLING_V5 = BILLING_V4.replace("\n# HACK: cache prices for 5 minutes\n", "")
BILLING_V5 += "# TODO: migrate off sqlite\n"

LEGACY_V1 = """\
# TODO: remove legacy shim once v2 ships
def shim(request):
    return request
"""

FLAGS_V1 = """\
# XXX: temp feature flag, remove after launch
FLAG_NEW_CHECKOUT = True
"""

COMMIT_PLAN = [
    # (date, author, {path: content or None to delete}, message, mv)
    ("2024-01-10T09:00:00 +0800", ALICE,
     {"billing.py": BILLING_V1}, "open the books: a FIXME and a TODO", None),
    ("2024-01-20T09:00:00 +0800", ALICE,
     {"billing.py": BILLING_V2, "legacy.py": LEGACY_V1},
     "hasty cache hack + legacy shim", None),
    ("2024-03-01T09:00:00 +0800", BOB,
     {"billing.py": BILLING_V3}, "pay the validation TODO", None),
    ("2025-03-01T09:00:00 +0800", ALICE,
     {"billing.py": BILLING_V4}, "promise metrics (someday)", None),
    ("2025-05-01T09:00:00 +0800", CHEN,
     {}, "move billing into src/", ("billing.py", "src/billing.py")),
    ("2025-06-01T09:00:00 +0800", BOB,
     {"src/billing.py": BILLING_V5}, "pay the cache hack; promise migration", None),
    ("2026-08-01T09:00:00 +0800", CHEN,
     {"legacy.py": None, "flags.py": FLAGS_V1},
     "delete legacy (its TODO dies); add temp flag", None),
]


def commit(repo, author, when, message, files, mv=None):
    for rel, content in files.items():
        full = os.path.join(repo, rel)
        if content is None:
            os.remove(full)
            continue
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w") as fh:
            fh.write(content)
    if mv:
        src, dst = mv
        os.makedirs(os.path.dirname(os.path.join(repo, dst)) or repo, exist_ok=True)
        subprocess.run(["git", "-C", repo, "mv", src, dst], check=True)
    env = dict(os.environ,
               GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
               GIT_COMMITTER_NAME=author[0], GIT_COMMITTER_EMAIL=author[1],
               GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-q", "-m", message],
                   check=True, env=env)


def build_repo(path):
    subprocess.run(["git", "init", "-q", path], check=True)
    for when, author, files, message, mv in COMMIT_PLAN:
        commit(path, author, when, message, files, mv)
    return path


def run_cli(repo, *args):
    proc = subprocess.run(list(CLI) + list(args), cwd=repo,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("CLI %s failed:\n%s%s" % (args, proc.stdout, proc.stderr))
    return proc.stdout


def sync_demo_tree(repo):
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    for src in sorted(Path(repo).rglob("*")):
        if ".git" in src.parts:
            continue
        rel = src.relative_to(repo)
        if src.is_dir():
            (DEMO / rel).mkdir(parents=True, exist_ok=True)
        else:
            (DEMO / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, DEMO / rel)


def check(label, cond):
    if not cond:
        raise SystemExit("sample out of sync: " + label)
    print("  ok  %s" % label)


def hard_asserts(repo):
    led = json.loads(run_cli(repo, "ledger", "--as-of", AS_OF, "--format", "json"))
    s = led["summary"]
    check("half-life 274.5 days", s["half_life_days"] == 274.5)
    check("2 promises paid, 1 died with its file",
          s["paid_promises"] == 2 and s["died_with_file"] == 1)
    check("4 promises outstanding",
          s["promises"] == 4 and sum(s["by_bucket"].values()) == 4)
    check("1 FRESH (xxx flag) / 3 ANCIENT",
          s["by_bucket"]["FRESH"] == 1 and s["by_bucket"]["ANCIENT"] == 3)
    check("exactly 1 zombie: the 951-day FIXME",
          s["zombies"] == 1
          and [p["marker"] for p in led["promises"] if p.get("zombie")] == ["FIXME"]
          and led["promises"][0]["age_days"] == 951
          and led["promises"][0]["file"] == "src/billing.py")
    check("total rust 13.2", s["total_rot"] == 13.2)
    by_author = {a["author"]: a for a in led["per_author"]}
    check("alice issued 4, 2 paid by others, 2 outstanding",
          by_author["Alice Chen"] == {"author": "Alice Chen", "issued": 4,
                                      "paid": 2, "outstanding": 2,
                                      "unpaid_rate": 0.5})
    check("rename preserved the FIXME's 2024-01-10 intro",
          led["promises"][0]["intro_date"] == "2024-01-10")
    half = json.loads(run_cli(repo, "halflife", "--as-of", AS_OF, "--format", "json"))
    check("zombie threshold 549 days in halflife view",
          half["summary"]["zombies"] == 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify samples without writing")
    args = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="todo-rot-demo-")
    try:
        repo = build_repo(tmp)
        ledger_txt = run_cli(repo, "ledger", "--as-of", AS_OF)
        halflife_txt = run_cli(repo, "halflife", "--as-of", AS_OF)
        hard_asserts(repo)
        if args.check:
            for name, want in (("sample-ledger.txt", ledger_txt),
                               ("sample-halflife.txt", halflife_txt)):
                got = (EX / name).read_text()
                check("%s byte-identical to committed sample" % name,
                      got == want)
            print("check passed — committed samples are in sync")
        else:
            (EX / "sample-ledger.txt").write_text(ledger_txt)
            (EX / "sample-halflife.txt").write_text(halflife_txt)
            sync_demo_tree(repo)
            print("wrote sample-ledger.txt, sample-halflife.txt, demo-repo/")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
