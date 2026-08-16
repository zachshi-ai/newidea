# demo-repo

A tiny fixture repo for doc-drift's examples and tests — it contains
deliberate drift on purpose (each bad line is marked DRIFT below).

<!-- verified: 2026-01-05; ttl: 90d -->                      <- DRIFT: stale (WARN)

Quick start — read the [guide](docs/guide.md), then:

```bash
python3 src/live.py --config config.toml
```

The entry point is `src/live.py::run_checks`.
Legacy rules used to live in `src/gone.py`.                 <- DRIFT: missing file
Older notes are in `old_notes.txt`.                         <- DRIFT: missing file
See the [FAQ](docs/missing.md) for details.                 <- DRIFT: missing link
Fallback entry: `src/live.py::gone_fn`.                     <- DRIFT: missing symbol
The archived `legacy/old_path.py` moved.  <!-- dd:ignore: kept for history -->
<!-- verified: 2026-12-01 -->                                <- DRIFT: future date
