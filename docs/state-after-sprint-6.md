# State After Sprint 6 (Mid-Loop Audit)

**Loop:** asset-tracker · **Tier:** RALPH (12 sprints) · **Date:** 2026-06-28

## What works
- **Schema v1**: 4 tables + `schema_meta`, FK constraints, indexes on hot columns.
- **Models**: dataclasses with built-in `validate()`, refund/non-refund net_amount rule, currency format check.
- **Repository**: full CRUD + idempotent inserts via `UNIQUE(channel_id, external_id)` + auto-fee from channel rules.
- **Metrics engine**: MRR, ARR, YTD, total, period fees, per-platform breakdown, per-project ROI (correctly scoped), time-to-income, daily trend.
- **CLI**: project/channel/tx/metrics/dashboard/backup/export/seed/integrations.
- **Tests**: 10/10 pass via `python3 tests/test_basics.py` (no pytest required).

## Bugs found and fixed during this half
1. **SQL cartesian product** (Sprint 6 audit) — `LEFT JOIN time_logs` was duplicating minutes per transaction. Replaced with scalar subqueries. ROI is now correct.
2. **Auto-fee skip on external_id** (Sprint 4) — thought external_id meant "re-import" but it's an idempotency key. Fixed.
3. **PY310 union syntax in stubs** — `cur.lastrowid: int | None` flagged by pyright; defensively cast to `int()`.

## What's not yet built (next 6 sprints)
- Sprint 7: backup/snapshot/seed-loaders (real impl, not placeholders).
- Sprint 8: TUI dashboard with box-drawing + coloring.
- Sprint 9: integration stubs (Stripe, Gumroad, Bandcamp, GitHub, Etsy).
- Sprint 10: edge cases + concurrent logging stress.
- Sprint 11: filters + CSV output.
- Sprint 12: README, final build, handover.

## Token spend
- Inline execution, no cron — zero tokens spent on cron infrastructure.
- Estimated total at completion: still well within single-session budget.
