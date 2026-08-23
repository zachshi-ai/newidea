#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild the witching-hour demo repository: one month of a three-person
startup, every timestamp pinned, so commit hashes and sample reports are
reproducible across machines.

The story (all +08:00 wall clock, March 2026):

  * alice works days: skeleton, config, api — solid volume, few bugs,
    and her bugs get fixed in daylight too.
  * bob is the night owl: three sessions at 02-03 am shipping billing /
    retry / worker code. Few lines, but 12 of them get fixed later —
    every one of his 00-03 lines that survived review carried a bug.
  * carol pays the friday-night tax: a production crash patched at
    23:30 on a friday (fixing alice's daytime bug, in the dark).

Run `python3 examples/build_examples.py` to rebuild `examples/demo-repo/`
(working tree only, .git stripped) and regenerate `examples/sample-*.txt`.
Run with `--check` to verify the committed tree and reports still match a
fresh rebuild (used by the acceptance suite).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import witching_hour as wh  # noqa: E402

PEOPLE = {
    "alice": ("Alice Zhang", "alice@demo.dev"),
    "bob": ("Bob Li", "bob@demo.dev"),
    "carol": ("Carol Wu", "carol@demo.dev"),
}


def commit(repo: str, who: str, when: str, msg: str) -> None:
    name, mail = PEOPLE[who]
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = when
    env["GIT_COMMITTER_DATE"] = when
    subprocess.run(
        ["git", "-C", repo, "-c", "user.name=%s" % name,
         "-c", "user.email=%s" % mail, "commit", "-q", "-m", msg],
        env=env, check=True,
    )


def write(repo: str, rel: str, lines: list) -> None:
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def add_all(repo: str) -> None:
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)


# --------------------------------------------------------------------------
# The month, commit by commit.  Bug lines carry `# BUG` comments so a human
# can spot them; witching-hour itself only ever sees the diffs.


def build(repo: str) -> None:
    subprocess.run(["git", "init", "-q", repo], check=True)

    # Mon 2026-03-02 10:12 — alice, skeleton (2 latent race lines, fixed 3/12)
    write(repo, "README.md", [
        "payments-demo", "==============", "",
        "A tiny service so witching-hour has a story to tell.", "",
    ])
    write(repo, "app.py", [
        "import config", "", "cache = {}", "running = True", "",
        "def handle(event):",
        "    if event.kind in cache:            # BUG: unsynchronized read",
        "        return cache[event.kind]",
        "    cache[event.kind] = process(event)  # BUG: unsynchronized write",
        "    return cache[event.kind]", "",
        "def process(event):",
        "    cfg = config.load()",
        "    return cfg.get(event.kind, None)", "",
        "def main():",
        "    while running:",
        "        handle(next_event())", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-02T10:12:00+08:00", "feat: project skeleton")

    # Mon 2026-03-02 15:40 — alice, config loader (3 typo lines, fixed 3/5)
    write(repo, "config.py", [
        "import json", "", "DEFAULTS = {",
        "    'retries': 3,",
        "    'timeout': 30,",
        "}", "",
        "def load():",
        "    cfg = dict(DEFAULTS)",
        "    cfg['retrys'] = cfg.pop('retries')   # BUG: key typo",
        "    cfg['timout'] = cfg.pop('timeout')   # BUG: key typo",
        "    return cfg", "",
        "def path_for(name):",
        "    return '/etc/demo/' + naem          # BUG: wrong name", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-02T15:40:00+08:00", "feat: config loader")

    # Tue 2026-03-03 02:47 — bob, billing skeleton in the witching hour
    # (6 bug lines, fixed 3/9 in daylight)
    write(repo, "src/billing.py", [
        "CURRENCY = 'CNY'", "",
        "def total(items):",
        "    s = 0",
        "    for i in range(1, len(items)):     # BUG: skips items[0]",
        "        s += items[i]['amount']", "    return s", "",
        "def apply_discount(total, pct):",
        "    return total - total / pct          # BUG: pct used as divisor",
        "",
        "def refund(order):",
        "    order.status = 'refunded'           # BUG: no idempotence guard",
        "    order.save()",
        "    return order.total * 1.0            # BUG: full amount always",
        "",
        "RATES = {'CNY': 1, 'USD': 7.2}",
        "def convert(amount, to):",
        "    return amount * RATES[to]",
        "",
        "def late_fee(days):",
        "    return days * 0.5 if days > 0 else days * -0.5  # BUG: sign flip",
        "",
    ])
    add_all(repo)
    commit(repo, "bob", "2026-03-03T02:47:00+08:00",
           "feat: billing skeleton")

    # Tue 2026-03-03 11:20 — alice, api endpoints (2 crash + 3 validation
    # bug lines, fixed 3/6 23:30 and 3/9 16:45)
    write(repo, "api.py", [
        "import json", "from app import handle", "",
        "ROUTES = {}", "",
        "def route(path):",
        "    def deco(fn):",
        "        ROUTES[path] = fn",
        "        return fn",
        "    return deco", "",
        "@route('/pay')",
        "def pay(req):",
        "    body = json.loads(req.body)          # BUG: no error handling",
        "    return handle(body)", "",
        "@route('/status')",
        "def status(req):",
        "    order = db.get(req.q['id'])          # BUG: db not imported",
        "    return order.status", "",
        "@route('/cancel')",
        "def cancel(req):",
        "    if not req.q.get('confirm'):         # BUG: missing else branch",
        "        return 'confirmation required'",
        "    return 'cancelled'", "",
        "def dispatch(req):",
        "    fn = ROUTES[req.path]                # BUG: KeyError on unknown",
        "    return fn(req)", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-03T11:20:00+08:00", "feat: api endpoints")

    # Wed 2026-03-04 03:12 — bob, retry logic at 3am (2 bug lines, fixed 3/11)
    write(repo, "retry.py", [
        "import time", "",
        "def with_retries(fn, args, attempts=3):",
        "    for i in range(attempts):",
        "        try:",
        "            return fn(*args)",
        "        except Exception:",
        "            time.sleep(i)                 # BUG: no backoff ceiling",
        "    raise RetryError('gave up after %d' % attemps)  # BUG: name typo",
        "",
        "class RetryError(Exception):",
        "    pass", "",
    ])
    add_all(repo)
    commit(repo, "bob", "2026-03-04T03:12:00+08:00", "wip: retry logic")

    # Wed 2026-03-04 14:00 — carol, docs and tests
    write(repo, "tests/test_app.py", [
        "from app import process", "",
        "class FakeEvent:",
        "    def __init__(self, kind):",
        "        self.kind = kind", "",
        "def test_process():",
        "    assert process(FakeEvent('pay')) is not None", "",
        "def test_process_unknown_kind():",
        "    assert process(FakeEvent('telepathy')) is None", "",
        "def test_process_empty_kind():",
        "    assert process(FakeEvent('')) is None", "",
        "def test_fake_event_carries_kind():",
        "    assert FakeEvent('pay').kind == 'pay'", "",
        "def test_process_is_pure_for_same_kind():",
        "    a = process(FakeEvent('pay'))",
        "    b = process(FakeEvent('pay'))",
        "    assert a == b", "",
        "def test_config_defaults_visible():",
        "    import config",
        "    assert config.DEFAULTS['retries'] == 3", "",
        "def test_config_timeout_sane():",
        "    import config",
        "    assert 0 < config.DEFAULTS['timeout'] <= 60", "",
        "def test_nothing_else():",
        "    # placeholder so the suite is not empty",
        "    assert True", "",
    ])
    add_all(repo)
    commit(repo, "carol", "2026-03-04T14:00:00+08:00", "docs + tests")

    # Thu 2026-03-05 10:30 — alice fixes her own daylight typos (3 lines)
    write(repo, "config.py", [
        "import json", "", "DEFAULTS = {",
        "    'retries': 3,",
        "    'timeout': 30,",
        "}", "",
        "def load():",
        "    cfg = dict(DEFAULTS)",
        "    return cfg", "",
        "def path_for(name):",
        "    return '/etc/demo/' + name", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-05T10:30:00+08:00",
           "fix: typos in config loader")

    # Fri 2026-03-06 23:30 — carol pays the friday-night tax: prod crash
    # from alice's unguarded json.loads, patched in the dark (2 lines)
    write(repo, "api.py", [
        "import json", "from app import handle", "",
        "ROUTES = {}", "",
        "def route(path):",
        "    def deco(fn):",
        "        ROUTES[path] = fn",
        "        return fn",
        "    return deco", "",
        "@route('/pay')",
        "def pay(req):",
        "    try:",
        "        body = json.loads(req.body)",
        "    except ValueError:",
        "        return 'bad payload'",
        "    return handle(body)", "",
        "@route('/status')",
        "def status(req):",
        "    order = db.get(req.q['id'])          # BUG: db not imported",
        "    return order.status", "",
        "@route('/cancel')",
        "def cancel(req):",
        "    if not req.q.get('confirm'):         # BUG: missing else branch",
        "        return 'confirmation required'",
        "    return 'cancelled'", "",
        "def dispatch(req):",
        "    fn = ROUTES[req.path]                # BUG: KeyError on unknown",
        "    return fn(req)", "",
    ])
    add_all(repo)
    commit(repo, "carol", "2026-03-06T23:30:00+08:00",
           "hotfix: prod crash on bad payload")

    # Mon 2026-03-09 09:15 — bob fixes the 02:47 billing sins (6 lines)
    write(repo, "src/billing.py", [
        "CURRENCY = 'CNY'", "",
        "def total(items):",
        "    s = 0",
        "    for item in items:",
        "        s += item['amount']", "    return s", "",
        "def apply_discount(total, pct):",
        "    return total * (1 - pct)", "",
        "def refund(order):",
        "    if order.status == 'refunded':",
        "        return order.refund_amount",
        "    order.status = 'refunded'",
        "    order.save()",
        "    return order.total", "",
        "RATES = {'CNY': 1, 'USD': 7.2}",
        "def convert(amount, to):",
        "    return amount * RATES[to]",
        "",
        "def late_fee(days):",
        "    return abs(days) * 0.5",
        "",
    ])
    add_all(repo)
    commit(repo, "bob", "2026-03-09T09:15:00+08:00",
           "fix: off-by-one and friends in billing")

    # Mon 2026-03-09 16:45 — alice fixes api validation (3 lines)
    write(repo, "api.py", [
        "import json", "from app import handle", "",
        "ROUTES = {}", "",
        "def route(path):",
        "    def deco(fn):",
        "        ROUTES[path] = fn",
        "        return fn",
        "    return deco", "",
        "@route('/pay')",
        "def pay(req):",
        "    try:",
        "        body = json.loads(req.body)",
        "    except ValueError:",
        "        return 'bad payload'",
        "    return handle(body)", "",
        "@route('/status')",
        "def status(req):",
        "    order = db.get(req.q['id'])          # BUG: db not imported",
        "    return order.status", "",
        "@route('/cancel')",
        "def cancel(req):",
        "    if not req.q.get('confirm'):",
        "        return 'confirmation required'",
        "    return 'cancelled'", "",
        "def dispatch(req):",
        "    fn = ROUTES.get(req.path)",
        "    if fn is None:",
        "        return 'not found'",
        "    return fn(req)", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-09T16:45:00+08:00",
           "fix: api validation gaps")

    # Tue 2026-03-10 02:15 — bob again at 2am, worker (4 bug lines, 3/13)
    write(repo, "worker.py", [
        "import queue", "",
        "TASKS = queue.Queue()",
        "STOP = False", "",
        "def loop():",
        "    while not STOP:",
        "        task = TASKS.get()",
        "        result = run(task)",
        "        if result == 'retry':            # BUG: re-enqueues forever",
        "            TASKS.put(task)",
        "",
        "def run(task):",
        "    return task()", "",
    ])
    add_all(repo)
    commit(repo, "bob", "2026-03-10T02:15:00+08:00", "wip: worker loop")

    # Wed 2026-03-11 10:00 — alice fixes the 3am retry storm (2 lines)
    write(repo, "retry.py", [
        "import time", "",
        "def with_retries(fn, args, attempts=3):",
        "    for i in range(attempts):",
        "        try:",
        "            return fn(*args)",
        "        except Exception:",
        "            time.sleep(min(i, 5))",
        "    raise RetryError('gave up after %d' % attempts)",
        "",
        "class RetryError(Exception):",
        "    pass", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-11T10:00:00+08:00", "fix: retry storm")

    # Thu 2026-03-12 15:00 — carol fixes the cache race from day one (2 lines)
    write(repo, "app.py", [
        "import config", "import threading", "", "cache = {}",
        "cache_lock = threading.Lock()", "running = True", "",
        "def handle(event):",
        "    with cache_lock:",
        "        if event.kind in cache:",
        "            return cache[event.kind]",
        "        cache[event.kind] = process(event)",
        "        return cache[event.kind]", "",
        "def process(event):",
        "    cfg = config.load()",
        "    return cfg.get(event.kind, None)", "",
        "def main():",
        "    while running:",
        "        handle(next_event())", "",
    ])
    add_all(repo)
    commit(repo, "carol", "2026-03-12T15:00:00+08:00",
           "fix: cache race in app")

    # Fri 2026-03-13 11:00 — bob fixes his own 2am worker bugs (4 lines)
    write(repo, "worker.py", [
        "import queue", "",
        "TASKS = queue.Queue()",
        "STOP = False",
        "MAX_ATTEMPTS = 3", "",
        "def loop():",
        "    while not STOP:",
        "        task = TASKS.get()",
        "        result = run(task)",
        "        if result == 'retry' and task.attempts < MAX_ATTEMPTS:",
        "            task.attempts += 1",
        "            TASKS.put(task)",
        "",
        "def run(task):",
        "    return task()", "",
    ])
    add_all(repo)
    commit(repo, "bob", "2026-03-13T11:00:00+08:00",
           "fix: worker bugs from the 2am session")

    # Mon 2026-03-16 10:30 — alice rewrites the flaky FakeEvent helper
    # (3 lines from carol's 03-04 session get new birth certificates)
    write(repo, "tests/test_app.py", [
        "from app import process, handle", "",
        "class FakeEvent:",
        "    def __init__(self, kind, payload=None):",
        "        self.kind = kind",
        "        self.payload = payload", "",
        "def test_process():",
        "    assert process(FakeEvent('pay')) is not None", "",
        "def test_process_unknown_kind():",
        "    assert process(FakeEvent('telepathy')) is None", "",
        "def test_process_empty_kind():",
        "    assert process(FakeEvent('')) is None", "",
        "def test_fake_event_carries_kind():",
        "    assert FakeEvent('pay').kind == 'pay'", "",
        "def test_process_is_pure_for_same_kind():",
        "    a = process(FakeEvent('pay'))",
        "    b = process(FakeEvent('pay'))",
        "    assert a == b", "",
        "def test_config_defaults_visible():",
        "    import config",
        "    assert config.DEFAULTS['retries'] == 3", "",
        "def test_config_timeout_sane():",
        "    import config",
        "    assert 0 < config.DEFAULTS['timeout'] <= 60", "",
        "def test_nothing_else():",
        "    # placeholder so the suite is not empty",
        "    assert True", "",
    ])
    add_all(repo)
    commit(repo, "alice", "2026-03-16T10:30:00+08:00",
           "fix: flaky FakeEvent helper")


def render_reports(repo: str) -> dict:
    res = wh.scan_repo(repo)
    res.repo = "demo-repo"  # pin the label: tmp paths must not leak into reports
    rhythm = wh.render_rhythm(wh.load_log(repo))
    birth = wh.render_birth(repo, "src/billing.py")
    return {
        "sample-scan.txt": wh.render_scan(res) + "\n",
        "sample-rhythm.txt": rhythm + "\n",
        "sample-birth.txt": birth + "\n",
    }


def tree_diff(a: str, b: str) -> bool:
    """True when the working trees (ignoring .git) are identical."""
    out = subprocess.run(
        ["diff", "-r", "-x", ".git", a, b],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if out.returncode != 0:
        sys.stderr.write(out.stdout.decode("utf-8", "replace"))
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify committed demo tree + reports match a rebuild")
    args = ap.parse_args(argv)

    demo = os.path.join(HERE, "demo-repo")
    tmp = tempfile.mkdtemp(prefix="wh-demo-")
    try:
        build(os.path.join(tmp, "demo-repo"))
        reports = render_reports(os.path.join(tmp, "demo-repo"))

        if args.check:
            if not os.path.isdir(demo):
                print("demo-repo/ missing; run without --check first")
                return 1
            if not tree_diff(demo, os.path.join(tmp, "demo-repo")):
                return 1
            for name, want in reports.items():
                path = os.path.join(HERE, name)
                if not os.path.exists(path):
                    print("%s missing" % name)
                    return 1
                with open(path) as fh:
                    if fh.read() != want:
                        print("%s out of sync; rebuild examples" % name)
                        return 1
            print("examples in sync")
            return 0

        if os.path.isdir(demo):
            shutil.rmtree(demo)
        shutil.copytree(os.path.join(tmp, "demo-repo"), demo,
                        ignore=shutil.ignore_patterns(".git"))
        for name, text in reports.items():
            with open(os.path.join(HERE, name), "w") as fh:
                fh.write(text)
        print("rebuilt examples/demo-repo + 3 sample reports")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
