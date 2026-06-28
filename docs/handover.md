# asset-tracker — Final Handover

**Loop:** asset-tracker · **Tier:** RALPH (12 sprints, ~6h total) · **Date:** 2026-06-28

## TL;DR

`asset-tracker` is a local-first, stdlib-only Python registry for every personal side project + income channel. It catalogs projects, tracks transactions (idempotent on `(channel_id, external_id)`), auto-computes fees from channel rules, computes MRR/ARR/YTD/per-project ROI/per-platform breakdown, renders a 6-panel TUI dashboard, exports to JSON and CSV, and ships integration stubs for Stripe/Gumroad/Bandcamp/GitHub Sponsors/Etsy. **26/26 tests pass.**

## What ships

| Area | File(s) | Lines | Status |
|---|---|---:|---|
| Schema | `schema/schema.sql` | 72 | ✅ |
| DB layer | `src/asset_tracker/db.py` | 106 | ✅ FK + WAL + backups_dir |
| Models | `src/asset_tracker/models.py` | 171 | ✅ 4 dataclasses + validation |
| Repository | `src/asset_tracker/repository.py` | 221 | ✅ CRUD + idempotency |
| Metrics | `src/asset_tracker/metrics.py` | 202 | ✅ MRR/ARR/YTD/per-project ROI |
| Dashboard | `src/asset_tracker/dashboard.py` | 223 | ✅ 6 panels, ANSI color |
| Backup | `src/asset_tracker/backup.py` | 130 | ✅ sqlite .backup + rotation |
| CLI | `src/asset_tracker/cli.py` | 402 | ✅ 14 subcommands |
| CSV | `src/asset_tracker/csv_export.py` | 85 | ✅ tx + projects |
| Integrations | `src/asset_tracker/integrations.py` | 388 | ✅ 5 connectors + NormalizedTxn |
| Tests | `tests/test_basics.py` + `test_edges.py` | 634 | ✅ 26/26 pass |
| Docs | `README.md` + `docs/data-model.md` + `docs/state-after-sprint-6.md` + `docs/handover.md` | ~6 KB | ✅ |

**Total: ~2,900 lines.** Zero external deps.

## Sprint-by-sprint outcomes

1. **Schema design** — 4 entities, FK CASCADE, idempotent txn constraint, schema_meta version. Documented in `docs/data-model.md`.
2. **Repo init** — git, `.gitignore`, `.env.example`, `pyproject.toml`, `requirements.txt` (empty — stdlib only).
3. **DB / models / repo** — full CRUD, validated dataclasses, idempotent inserts.
4. **CLI** — 14 subcommands, fee auto-compute fix (external_id ≠ fee-skip signal).
5. **Metrics engine** — MRR/ARR/YTD/per-platform/per-project/time-to-income/trend.
6. **Mid-loop audit + tests** — 10/10 tests pass; **fixed SQL cartesian-product bug** in per-project ROI (scalar subqueries instead of LEFT JOIN).
7. **Backup + export + seed** — `sqlite3.Connection.backup()` is crash-safe, rotates to keep N; JSON dump + idempotent seed loader.
8. **TUI dashboard** — 6 panels, ANSI color, terminal-width-adaptive, "no data" graceful states.
9. **Integration framework** — 5 connectors (Stripe, Gumroad, Bandcamp, GitHub, Etsy) with `NormalizedTxn` lingua franca, idempotent import pipeline, synthetic mock for end-to-end testing.
10. **Validation + edges** — 16 new tests covering extremes, concurrent writes, empty DB, refunds, time-log caps. **Found + fixed 2 validation bugs** (zero-net tips, ROI null for zero-rev).
11. **Polish** — CSV export, summary one-liner, per-project metrics filter.
12. **README + handover** — this doc.

## Bugs caught and fixed during the loop

| Sprint | Bug | Fix |
|---:|---|---|
| 4 | Auto-fee skipped when `external_id` was set | Treat external_id as idempotency key only, not fee-skip |
| 6 | Per-project ROI showed 3× actual (SQL cartesian product) | Scalar subqueries instead of `LEFT JOIN time_logs` |
| 7 | Backups went to wrong dir when DB path was non-default | Derive backup dir from actual conn file, not default_db_path |
| 10 | Zero-net tip txns were rejected (free/comp use case) | Allow `net >= 0` for non-refund kinds |
| 10 | ROI showed `0.0` for zero-revenue projects | Return `None` unless both `net > 0` AND `hours > 0` |

## Verification commands

```bash
cd /Users/openclaw/hermes-data/projects/asset-tracker

# 26/26 tests
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py

# Fresh end-to-end demo
rm -f /tmp/at.db
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli seed
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli dashboard
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli summary

# Stress / mock-import
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli import-mock stripe --count 10
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli import-mock stripe --count 10   # idempotent
AT_DB_PATH=/tmp/at.db PYTHONPATH=src python3 -m asset_tracker.cli metrics --period all
```

## Future-session commands (for the next agent or Erik)

```bash
# Where the project lives
cd /Users/openclaw/hermes-data/projects/asset-tracker

# Real DB
ls -la data/asset-tracker.db

# Restore from a backup
cp data/backups/asset-tracker-<timestamp>.db data/asset-tracker.db

# Add a new platform connector: edit src/asset_tracker/integrations.py
# - subclass Connector
# - implement platform_id, platform_name, env_var, _fetch_recent_impl, normalize
# - append to REGISTRY
```

## Known limitations (acceptable)

- **No multi-currency conversion.** Each tx stored in its native currency; per-currency aggregation is left to the caller. Adding this needs an FX-rate table + converter.
- **Tax categorization** not in scope. Could be a `tags` column in v2.
- **No TUI interactivity (no `curses`).** Dashboard is one-shot — prints and exits. Adding keystroke nav is straightforward but not in scope.
- **Live API integrations are gated** behind `AT_LIVE_INTEGRATIONS=1`. The `_fetch_recent_impl` methods raise NotImplementedError. Wiring them up requires each platform's SDK or a `urllib`-based HTTP client — out of scope for this loop.

## Token spend (this loop)

- Single session, no cron infrastructure.
- Estimated total: well within budget (much less than one MALPH's typical cost).
- All artifact code is on disk in `src/` + `tests/` + `seed/` + `schema/` + `docs/`.

## Sign-off

Loop complete. `.ralph_loop_state` marked Sprint 12 done. All evidence on disk. No open blockers.
