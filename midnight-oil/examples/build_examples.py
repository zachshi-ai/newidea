#!/usr/bin/env python3
"""Build the midnight-oil demo repo + sample reports (reproducible).

三人迷你仓库, 日期/钟点/时区全部钉死 (GIT_AUTHOR_DATE), 用于:

  Alice Chen  健康作息: 工作日上午, 零深夜零周末           -> ok
  Bob Wu      过劳恶化: baseline 全白天, 近 13 周深夜+周末
              + 16 天连轴 + 7 个周末深夜日                 -> alert
  Carol Diaz  稳定夜猫子: 全程 -0500 凌晨, 前后一致        -> watch
              (trend = STABLE: 夜猫子辩护的活例子)

  --check  重建并逐字节校验已提交的样例 (供 CI / ExamplesSyncTests)
  (无参数) 重建并把样例写回 examples/
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = [sys.executable, os.path.join(ROOT, "midnight_oil.py")]
DEMO = os.path.join(HERE, "demo-repo")
AS_OF = "2026-08-24"

ALICE = ("Alice Chen", "alice@example.com")
BOB = ("Bob Wu", "bob@example.com")
CAROL = ("Carol Diaz", "carol@example.com")

TREND_CUTOFF = date(2026, 5, 25)   # as_of - 91d: 近 13 周为 recent 段


def days(start, end, step_days=1):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=step_days)


def weekly(start, end, weekdays):
    for d in days(start, end):
        if d.weekday() in weekdays:
            yield d


# Alice: 周一三五 10:00 (+0800)
ALICE_PLAN = [("{} 10:00:00 +0800".format(d.isoformat()), ALICE,
               "docs: weekly note {}".format(d))
              for d in weekly(date(2026, 3, 2), date(2026, 8, 19), (0, 2, 4))]

# Bob baseline: 周一三五 11:00, 全白天 (+0800)
BOB_BASE = [("{} 11:00:00 +0800".format(d.isoformat()), BOB,
             "feat: daytime work {}".format(d))
            for d in weekly(date(2026, 3, 2), date(2026, 5, 22), (0, 2, 4))]

# Bob recent: 每周三/五深夜 + 周六白天照常出勤 + 16+ 天连轴 (6-01..6-16)
# + 7 个周末深夜日
BOB_RECENT = []
for d in weekly(date(2026, 5, 25), date(2026, 8, 21), (2, 4)):
    BOB_RECENT.append(("{} 23:40:00 +0800".format(d.isoformat()), BOB,
                       "fix: shipping late again"))
for d in weekly(date(2026, 5, 25), date(2026, 8, 21), (5,)):
    BOB_RECENT.append(("{} 10:30:00 +0800".format(d.isoformat()), BOB,
                       "chore: saturday office hours"))
for d in days(date(2026, 6, 1), date(2026, 6, 16)):
    BOB_RECENT.append(("{} 01:10:00 +0800".format(d.isoformat()), BOB,
                       "feat: deadline sprint {}".format(d)))
WEEKEND_LATE = [
    (date(2026, 6, 6), "23:40:00"), (date(2026, 6, 7), "00:10:00"),
    (date(2026, 6, 14), "23:50:00"), (date(2026, 7, 4), "23:30:00"),
    (date(2026, 7, 5), "00:15:00"), (date(2026, 8, 8), "23:45:00"),
    (date(2026, 8, 9), "00:05:00"),
]
for d, hm in WEEKEND_LATE:
    BOB_RECENT.append(("{} {} +0800".format(d.isoformat(), hm), BOB,
                       "hotfix: can't stop thinking about it"))

# Carol: 周二/四 00:15 或 01:00 (她本地 -0500), 全程一致
CAROL_PLAN = []
for d in weekly(date(2026, 3, 2), date(2026, 8, 20), (1, 3)):
    hm = "00:15:00" if d.weekday() == 1 else "01:00:00"
    CAROL_PLAN.append(("{} {} -0500".format(d.isoformat(), hm), CAROL,
                       "refactor: quiet hours are my hours"))

PLAN = ALICE_PLAN + BOB_BASE + BOB_RECENT + CAROL_PLAN
# 报告输出按时间排序, 仓库内提交顺序也按时间排 (叙事一致)
PLAN.sort(key=lambda item: item[0])


def build_repo(path):
    subprocess.run(["git", "init", "-q", path], check=True)
    per_author = {}
    for when, author, message in PLAN:
        name, email = author
        rel = "notes/{}.md".format(name.split()[0].lower())
        full = os.path.join(path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a") as fh:
            fh.write("- {} {}\n".format(when, message))
        env = dict(os.environ,
                   GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email,
                   GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        subprocess.run(["git", "-C", path, "add", "-A"], check=True)
        subprocess.run(["git", "-C", path, "commit", "-q", "-m", message],
                       check=True, env=env)
        per_author[name] = per_author.get(name, 0) + 1
    return path


def run_cli(repo, *args, expect=0):
    proc = subprocess.run(CLI + list(args), cwd=repo,
                          capture_output=True, text=True)
    if proc.returncode != expect:
        raise SystemExit("CLI {} rc={}:\n{}{}".format(
            args, proc.returncode, proc.stdout, proc.stderr))
    return proc.stdout


def sync_demo_tree(repo):
    if os.path.exists(DEMO):
        shutil.rmtree(DEMO)
    os.makedirs(DEMO)
    for base, dirs, files in os.walk(repo):
        if ".git" in base.split(os.sep):
            continue
        for name in files:
            src = os.path.join(base, name)
            rel = os.path.relpath(src, repo)
            dst = os.path.join(DEMO, rel)
            os.makedirs(os.path.dirname(dst) or DEMO, exist_ok=True)
            shutil.copy2(src, dst)


def check(label, cond):
    if not cond:
        raise SystemExit("sample out of sync: " + label)
    print("  ok  {}".format(label))


def hard_asserts(repo):
    scan = json.loads(run_cli(repo, "scan", "--as-of", AS_OF,
                              "--format", "json"))
    check("3 authors in the demo", scan["authors"] == 3)
    check("repo level is alert (Bob drags it)", scan["level"] == "alert")

    auth = json.loads(run_cli(repo, "authors", "--as-of", AS_OF,
                              "--format", "json"))
    by = {a["author"]: a for a in auth["authors"]}

    check("Alice: zero flags, ok", by["Alice Chen"]["flags"] == []
          and by["Alice Chen"]["level"] == "ok"
          and by["Alice Chen"]["late_pct"] == 0.0
          and by["Alice Chen"]["weekend_pct"] == 0.0)

    check("Bob: all four flags, alert, 17-day streak",
          by["Bob Wu"]["flags"] == ["LATE_NIGHT", "WEEKENDS", "NO_BREAK",
                                    "WEEKEND_LATE"]
          and by["Bob Wu"]["level"] == "alert"
          and by["Bob Wu"]["longest_streak_days"] == 17
          and len(by["Bob Wu"]["weekend_late_days"]) == 8
          and by["Bob Wu"]["weekend_pct"] == 23.7)

    check("Carol: night owl with exactly one flag, watch",
          by["Carol Diaz"]["flags"] == ["LATE_NIGHT"]
          and by["Carol Diaz"]["level"] == "watch"
          and by["Carol Diaz"]["late_pct"] == 100.0
          and by["Carol Diaz"]["weekend_pct"] == 0.0)

    bob_trend = json.loads(run_cli(repo, "trend", "--as-of", AS_OF,
                                   "--author", "Bob Wu", "--format", "json"))
    check("Bob's late-night trend is WORSENING (0% -> majority)",
          bob_trend["directions"]["late"] == "WORSENING"
          and bob_trend["baseline"]["late_pct"] == 0.0)

    carol_trend = json.loads(run_cli(repo, "trend", "--as-of", AS_OF,
                                     "--author", "Carol Diaz",
                                     "--format", "json"))
    check("Carol's late-night trend is STABLE — the night-owl defense",
          carol_trend["directions"]["late"] == "STABLE")

    run_cli(repo, "audit", "--as-of", AS_OF, expect=1)
    check("audit gates: demo repo exceeds default budget", True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify samples without writing")
    args = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="midnight-oil-demo-")
    try:
        repo = build_repo(tmp)
        samples = {
            "sample-scan.txt": run_cli(repo, "scan", "--as-of", AS_OF),
            "sample-authors.txt": run_cli(repo, "authors", "--as-of", AS_OF),
            "sample-trend.txt": run_cli(repo, "trend", "--as-of", AS_OF,
                                        "--author", "Bob Wu"),
        }
        hard_asserts(repo)
        if args.check:
            for name, want in samples.items():
                with open(os.path.join(HERE, name)) as fh:
                    check("{} byte-identical to committed sample"
                          .format(name), fh.read() == want)
            print("check passed — committed samples are in sync")
        else:
            for name, text in samples.items():
                with open(os.path.join(HERE, name), "w") as fh:
                    fh.write(text)
            sync_demo_tree(repo)
            print("wrote sample-*.txt + demo-repo/")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
