## Summary

What changed and why?

## Test plan

- [ ] `PYTHONPATH=src python3 tests/test_basics.py`
- [ ] `PYTHONPATH=src python3 tests/test_edges.py`
- [ ] `PYTHONPATH=src python3 tests/test_daily.py`
- [ ] `PYTHONPATH=src python3 tests/test_integrations.py`
- [ ] `pip install -e . && asset-tracker doctor` (if CLI touched)

## Notes

Stdlib-only constraint preserved: **yes / no**
