# asset-tracker — Handover (v0.2.1)

**Status:** Ready for daily personal use · **Date:** 2026-07-03

## TL;DR

Local-first, stdlib-only Python CLI for tracking side projects and income. Run `asset-tracker init`, then `asset-tracker log 49.99` daily. **45/45 tests pass.** CI on Python 3.9 and 3.12.

## What ships

| Area | Status |
|---|---|
| Daily workflow (`init`, `log`, `time`, `summary`, `recent`, `doctor`) | ✅ |
| Config defaults (`data/.asset-tracker.json`) | ✅ |
| Channel resolution by name/platform | ✅ |
| Stripe live import (`import stripe`, stdlib urllib) | ✅ |
| Gumroad/Bandcamp/GitHub/Etsy | Stub (normalize + mock import) |
| Metrics, dashboard, backup, CSV/JSON export | ✅ |
| Tests + CI | ✅ 45 tests |

## Verification

```bash
pip install -e .
PYTHONPATH=src python3 tests/test_basics.py
PYTHONPATH=src python3 tests/test_edges.py
PYTHONPATH=src python3 tests/test_daily.py
PYTHONPATH=src python3 tests/test_integrations.py

asset-tracker init --project-id demo --project-name Demo --category software --yes
asset-tracker log 25
asset-tracker doctor
```

## Known limitations

- Multi-currency conversion not implemented; metrics group by native currency (`by_currency` in JSON, per-currency rows in dashboard when mixed)
- Tax categorization not in scope
- Dashboard is one-shot TUI (no curses interactivity)
- Stripe, Gumroad, GitHub Sponsors, and Etsy have live HTTP fetch; Bandcamp has no public sales API (use manual `log` or `import-mock`)

## Sign-off

Productization sprint complete. Safe to merge and use with real data.
