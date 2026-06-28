"""
create-ralph-jobs.py — Create 12 asset-tracker-rerun cron jobs (one per sprint).

Each job is a 30-min cadence, scheduled to fire at 5-minute intervals from the
start time. The first run starts at NOW+1min; subsequent runs are spaced so the
total wall clock is ~6h.

The run prompt is the canonical ralph-loop template with the
`6. Exit - the next cron run will pick up from the updated state.` anchor,
which the harness script (`ralph-optimize-prompts.py`) targets for injection
of per-run token logging + cache-control discipline blocks.

Workdir is `/Users/openclaw/hermes-data` (internal disk, NOT the SSD wedge trap).
The run prompt cd's into the project dir explicitly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/Users/openclaw/.hermes/hermes-agent")
from cron.jobs import create_job  # type: ignore


SLUG = "asset-tracker-rerun"
PROJECT_DIR = "/Users/openclaw/hermes-data/projects/asset-tracker"
TOTAL_RUNS = 12
CADENCE_MIN = 30  # 30-min wall clock between runs
FIRST_OFFSET_MIN = 1  # first run starts 1 min from now


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def build_prompt(run_num: int) -> str:
    return f"""You are Run {run_num} of 12 in the asset-tracker-rerun RALPH loop.

## Context

The asset-tracker project was originally built inline (no cron) and shipped 12/12
sprints with 26/26 tests passing. The artifact is on disk at:
  /Users/openclaw/hermes-data/projects/asset-tracker/

This RALPH rerun re-executes the same 12 sprints as 12 separate 30-min cron-fired
subagents. Your job: verify the prior work for your sprint is on disk, surface
any delta (bug the original missed, test that fails on cold-rerun, etc.), and
update state before exit. If everything is intact, mark the sprint done in
`.ralph_loop_state` and exit.

## Read first (cache-control discipline)

1. Read RALPH-SUMMARY.md (1.4KB) — has the full sprint plan + state.
2. Read RALPH.md ONLY if the summary is stale or your task references a section
   not in the summary.
3. Read `.ralph_loop_state` to find your sprint's current status.

DO NOT re-read RALPH.md unless necessary — that's the cache-control lever.

## Your sprint ({run_num} of 12)

{{sprint_body}}

## Verification

Run BOTH test files. If either fails, that's a delta — fix it (or document why
it can't be fixed in this run) and update `.ralph_loop_state` with the finding.

```bash
cd {PROJECT_DIR}
PYTHONPATH=src /usr/bin/python3 tests/test_basics.py
PYTHONPATH=src /usr/bin/python3 tests/test_edges.py
```

## Tools

- terminal (run commands, git, python)
- file (read/write/edit project files)
- web (only if a sprint explicitly needs it — none of the 12 do)

## When done

1. Update `.ralph_loop_state`: set sprint {run_num} status to "completed" with
   a one-line evidence note (what you verified, any deltas found).
2. Append one line to `## Run log` in RALPH.md (date, run#, what you did, what
   you found).
3. If you found a delta, append one line to `## Learnings` in RALPH.md.
4. If this is the FINAL run (run 12), also write `.ralph-complete` as a
   sentinel file: `touch {PROJECT_DIR}/.ralph-complete`.
5. **Log per-run token spend (optimization harness):** Query
   `~/.hermes/state.db` for THIS session's token totals, append a one-line
   summary to RALPH.md's `## Usage / Budget Log` section:
   ```sql
   SELECT input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
     FROM sessions WHERE id = <this_session_id>
   ```
6. **Cache-control discipline:** read RALPH-SUMMARY.md by default; only re-read
   full RALPH.md if summary is >2 runs stale OR the task references a section
   not in the summary.
7. Exit - the next cron run will pick up from the updated state.
"""


SPRINT_BODIES = {
    1: """**Sprint 1 — Requirements & Schema Definition.**
Verify these files exist with the expected content:
- `schema/schema.sql` — should define 4 tables (projects, income_channels,
  transactions, time_logs) + schema_meta + indexes.
- `docs/data-model.md` — should describe all 4 entities with field tables,
  derived metrics, and out-of-scope items.
If both exist and match the spec, mark Sprint 1 done. If anything is missing
or wrong, surface the delta.""",

    2: """**Sprint 2 — Environment & Repository Initialization.**
Verify these files exist and the git repo is initialized:
- `.gitignore` — should ignore __pycache__, *.db, .venv/, etc.
- `.env.example` — should show AT_DB_PATH, AT_LOG_LEVEL, AT_BACKUP_KEEP
  plus optional integration env vars.
- `pyproject.toml` — should declare the asset-tracker package.
- `requirements.txt` — should be stdlib-only.
- `git log` should show 12+ commits (the prior inline run).
If anything is missing, surface the delta.""",

    3: """**Sprint 3 — Core Data Models.**
Verify these source files exist and import cleanly:
- `src/asset_tracker/db.py` — connect(), init_schema(), get_schema_version(),
  integrity_check(), table_counts(), backups_dir(), snapshot_to().
- `src/asset_tracker/models.py` — Project, IncomeChannel, Transaction,
  TimeLog dataclasses with validate() methods.
- `src/asset_tracker/repository.py` — CRUD functions: create_project,
  get_project, list_projects, update_project, delete_project, create_channel,
  list_channels, get_channel, create_transaction (idempotent), list_transactions,
  create_time_log, list_time_logs.

Smoke test: `cd {PROJECT_DIR} && PYTHONPATH=src /usr/bin/python3 -c "
import sys; sys.path.insert(0,'src')
from asset_tracker import db, models, repository
print('imports OK')
"`. Mark Sprint 3 done if all imports succeed.""",

    4: """**Sprint 4 — CLI / Input Interface.**
Verify `src/asset_tracker/cli.py` exists and exposes 14 subcommands via
`python3 -m asset_tracker.cli --help`. The subcommands should be:
project (add, list, show, update), channel (add, list), tx (log, list),
metrics, dashboard, backup, export, export-csv, summary, integrations,
import-mock, seed.

Smoke test: `cd {PROJECT_DIR} && PYTHONPATH=src /usr/bin/python3 -m
asset_tracker.cli --help | grep -c '{' subcommand` (should be 11+).
Mark Sprint 4 done if CLI loads and lists all subcommands.""",

    5: """**Sprint 5 — Calculation & Analytics Engine.**
Verify `src/asset_tracker/metrics.py` exists and compute_metrics() returns
the full metric set: mrr, arr, period_net, period_fees, ytd_net, ytd_fees,
total_net, total_fees, per_platform, per_project, time_to_income, trend.

Smoke test against the seeded DB:
```bash
cd {PROJECT_DIR}
AT_DB_PATH=data/asset-tracker.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli metrics --period all
```
Should produce a JSON dict with all 12 fields. Mark Sprint 5 done if metrics
emits the full structure.""",

    6: """**Sprint 6 — Mid-Loop Audit & State Serialization.**
Verify `tests/test_basics.py` exists and ALL 10 TESTS PASS:
```bash
cd {PROJECT_DIR}
PYTHONPATH=src /usr/bin/python3 tests/test_basics.py
```
The output should end with `=== 10 passed, 0 failed ===`. If any fail, that's
a delta — the inline run shipped this passing; a cold-rerun should too.
Mark Sprint 6 done if 10/10 pass.""",

    7: """**Sprint 7 — Persistence Layer Stabilization.**
Verify `src/asset_tracker/backup.py` exists with snapshot(), export_json(),
load_seed() functions. Also verify the seed loader works:
```bash
cd {PROJECT_DIR}
rm -f /tmp/at-backup.db
AT_DB_PATH=/tmp/at-backup.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli seed
AT_DB_PATH=/tmp/at-backup.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli backup
ls -la /tmp/backups/  # or wherever AT_DB_PATH resolves
```
Mark Sprint 7 done if seed + backup both produce files.""",

    8: """**Sprint 8 — Dashboard / Reporting View.**
Verify `src/asset_tracker/dashboard.py` exists and renders 6 panels:
```bash
cd {PROJECT_DIR}
AT_DB_PATH=data/asset-tracker.db AT_NO_COLOR=1 PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli dashboard 2>&1 | head -40
```
Output should contain: "asset-tracker", "Top metrics", "By platform",
"By project", "Active income channels", "Recent transactions", "Time to first
income". Mark Sprint 8 done if all 6 panels render.""",

    9: """**Sprint 9 — Extensibility Framework.**
Verify `src/asset_tracker/integrations.py` exists with 5 connectors
(Stripe, Gumroad, Bandcamp, GitHub Sponsors, Etsy) and import_mock() works:
```bash
cd {PROJECT_DIR}
AT_DB_PATH=/tmp/at-int.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli seed > /dev/null
AT_DB_PATH=/tmp/at-int.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli import-mock stripe --count 3
AT_DB_PATH=/tmp/at-int.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli import-mock stripe --count 3  # idempotent
```
Second import should report `skipped=3`. Mark Sprint 9 done if idempotency
holds.""",

    10: """**Sprint 10 — Validation & Error Handling.**
Verify `tests/test_edges.py` exists and ALL 16 TESTS PASS:
```bash
cd {PROJECT_DIR}
PYTHONPATH=src /usr/bin/python3 tests/test_edges.py
```
The output should end with `=== 16 passed, 0 failed ===`. If any fail, that's
a delta. Mark Sprint 10 done if 16/16 pass.""",

    11: """**Sprint 11 — Interface Polish & Configuration.**
Verify `src/asset_tracker/csv_export.py` exists and both CSV exports work:
```bash
cd {PROJECT_DIR}
AT_DB_PATH=data/asset-tracker.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli summary
AT_DB_PATH=data/asset-tracker.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli export-csv tx /tmp/at-tx-rerun.csv --project skull-telegram-gateway
AT_DB_PATH=data/asset-tracker.db PYTHONPATH=src /usr/bin/python3 -m asset_tracker.cli export-csv projects /tmp/at-proj-rerun.csv --status active
head -3 /tmp/at-tx-rerun.csv
head -3 /tmp/at-proj-rerun.csv
```
Both CSVs should have a header row. Mark Sprint 11 done if summary + both
CSVs work.""",

    12: """**Sprint 12 — Loop Review, Final Build, & Handover Documentation.**
Verify the final-state deliverables exist:
- `README.md` — should document the CLI + 14 commands + tests.
- `docs/handover.md` — should have the sprint ledger + verification commands.
- `.ralph_loop_state` — all 12 sprints should be `status: "completed"`.

Final test sweep:
```bash
cd {PROJECT_DIR}
PYTHONPATH=src /usr/bin/python3 tests/test_basics.py
PYTHONPATH=src /usr/bin/python3 tests/test_edges.py
```
Both should pass (10/10 + 16/16). Mark Sprint 12 done. **Write the
`.ralph-complete` sentinel**: `touch /Users/openclaw/hermes-data/projects/asset-tracker/.ralph-complete`.""",
}


def main() -> int:
    now = datetime.now(timezone.utc)
    first = now + timedelta(minutes=FIRST_OFFSET_MIN)
    created = 0
    for i in range(1, TOTAL_RUNS + 1):
        fire_at = first + timedelta(minutes=(i - 1) * CADENCE_MIN)
        # Stagger by 0/3/6 minutes per index to avoid minute-clash with other loops
        fire_at = fire_at + timedelta(minutes=(i % 3))
        body = SPRINT_BODIES[i]
        prompt = build_prompt(i).replace("{sprint_body}", body)
        job = create_job(
            name=f"{SLUG}-run-{i:02d}",
            prompt=prompt,
            schedule=_iso(fire_at),
            repeat=1,
            deliver="local",
            workdir="/Users/openclaw/hermes-data",
            enabled_toolsets=["terminal", "file", "web"],
        )
        print(f"  created run-{i:02d} → {fire_at.isoformat(timespec='seconds')}  id={job['id']}")
        created += 1
    return created


if __name__ == "__main__":
    n = main()
    print(f"\nCreated {n} jobs.")
