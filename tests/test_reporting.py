"""
test_reporting.py — Wave 3 reporting, rollup export, and enhanced recent.

Execute: PYTHONPATH=src python3 tests/test_reporting.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import traceback
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from asset_tracker import cli, csv_export, db, metrics, models, onboard, report, repository


PASSED = 0
FAILED = 0


def _record(name, fn):
    global PASSED, FAILED
    try:
        fn()
        PASSED += 1
        print(f"  PASS  {name}")
    except Exception:
        FAILED += 1
        print(f"  FAIL  {name}")
        traceback.print_exc()


def _fresh_env():
    td = tempfile.TemporaryDirectory()
    db_path = Path(td.name) / "test.db"
    os.environ["AT_DB_PATH"] = str(db_path)
    conn = db.connect()
    db.init_schema(conn)
    return td, conn


def test_period_windows_month_and_quarter():
    now = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
    original = metrics._now
    metrics._now = lambda: now
    try:
        m_start, m_end = metrics._period_window("month")
        assert m_start == datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert m_end == now

        q_start, q_end = metrics._period_window("quarter")
        assert q_start == datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert q_end == now

        p_start, p_end = metrics.prior_period_window("month")
        assert p_start == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert p_end.month == 6 and p_end.day == 30
    finally:
        metrics._now = original


def test_delta_new_when_prior_zero():
    d = report._delta(100.0, 0.0)
    assert d["label"] == "new"
    assert d["absolute"] == 100.0
    assert d["percent"] is None
    d2 = report._delta(0.0, 0.0)
    assert d2["label"] == "n/a"
    assert d2["percent"] is None
    d3 = report._delta(150.0, 100.0)
    assert d3["label"] is None
    assert d3["percent"] == 50.0
    assert d3["absolute"] == 50.0
    d4 = report._delta(80.0, 100.0)
    assert d4["percent"] == -20.0
    assert report._format_delta(d) == "new"
    assert report._format_delta(d2) == "n/a"
    assert report._format_delta(d3) == "+50.0%"
    assert report._format_delta(d4) == "-20.0%"


def test_empty_db_report_renders():
    td, conn = _fresh_env()
    try:
        rep = report.build_report(conn, period="30d", compare=True)
        text = report.format_report(rep)
        assert "Summary" in text or "asset-tracker report" in text
        assert rep["delta"]["period_net"]["label"] == "n/a"
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_multi_currency_report_delta():
    td, conn = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="p1", name="P1", category="software", status="active",
        ))
        repository.create_project(conn, models.Project(
            id="p2", name="P2", category="music", status="active",
        ))
        c_usd = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p1", name="USD sales", platform="direct",
            kind="one_time", currency="USD",
        ))
        c_eur = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p2", name="EUR sales", platform="direct",
            kind="one_time", currency="EUR",
        ))
        now = datetime.now(timezone.utc)
        prior = (now - timedelta(days=45)).isoformat(timespec="seconds")
        current = now.isoformat(timespec="seconds")
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p1", channel_id=c_usd,
            occurred_at=current, gross_amount=50, net_amount=50,
            currency="USD", kind="one_time",
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p2", channel_id=c_eur,
            occurred_at=current, gross_amount=40, net_amount=40,
            currency="EUR", kind="one_time",
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p1", channel_id=c_usd,
            occurred_at=prior, gross_amount=20, net_amount=20,
            currency="USD", kind="one_time",
        ))
        rep = report.build_report(conn, period="30d", compare=True)
        currencies = {row["currency"] for row in rep["by_currency"]}
        assert "USD" in currencies
        assert "EUR" in currencies
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_rollup_csv_header_and_rows():
    td, conn = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="p1", name="P1", category="software", status="active",
        ))
        cid = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="p1", name="Sales", platform="gumroad",
            kind="one_time", currency="USD", fee_pct=0.10,
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p1", channel_id=cid,
            occurred_at="2026-03-15T12:00:00+00:00",
            gross_amount=100, net_amount=90, fee_amount=10,
            currency="USD", kind="one_time",
        ))
        out = Path(td.name) / "rollup.csv"
        n = csv_export.export_rollup_csv(conn, out, year=2026)
        assert n == 1
        lines = out.read_text().strip().splitlines()
        assert lines[0] == "month,project_id,platform,currency,gross,fees,net,tx_count"
        assert "2026-03,p1,gumroad,USD,100.0,10.0,90.0,1" in lines[1]
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_cli_report_json_keys():
    td, conn = _fresh_env()
    try:
        onboard.run_init(conn, interactive=False, project_id="app", project_name="App", category="software")
        cli.main(["log", "25"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["report", "--json", "--no-compare"])
        data = json.loads(buf.getvalue())
        assert "current" in data
        assert "delta" in data
        assert "highlights" in data
        assert "sparkline" in data
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_recent_per_project_summary():
    td, conn = _fresh_env()
    try:
        repository.create_project(conn, models.Project(
            id="alpha", name="Alpha", category="software", status="active",
        ))
        repository.create_project(conn, models.Project(
            id="beta", name="Beta", category="music", status="active",
        ))
        c1 = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="alpha", name="A", platform="direct", kind="one_time",
        ))
        c2 = repository.create_channel(conn, models.IncomeChannel(
            id=None, project_id="beta", name="B", platform="direct", kind="one_time",
        ))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="alpha", channel_id=c1,
            occurred_at=now, gross_amount=99.99, net_amount=99.99,
            currency="USD", kind="one_time",
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="beta", channel_id=c2,
            occurred_at=now, gross_amount=50, net_amount=50,
            currency="USD", kind="one_time",
        ))
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["recent", "--days", "7"])
        out = buf.getvalue()
        assert "By project:" in out
        assert "alpha" in out
        assert "beta" in out
        assert "99.99" in out
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def test_doctor_monthly_review_tip():
    td, conn = _fresh_env()
    try:
        onboard.run_init(conn, interactive=False, project_id="app", project_name="App", category="software")
        cli.main(["log", "10"])
        text = onboard.run_doctor(conn)
        assert "report --period month" in text
    finally:
        conn.close()
        td.cleanup()
        os.environ.pop("AT_DB_PATH", None)


def main():
    print("test_reporting.py")
    _record("period windows: month and quarter", test_period_windows_month_and_quarter)
    _record("delta: new when prior zero", test_delta_new_when_prior_zero)
    _record("empty DB report renders", test_empty_db_report_renders)
    _record("multi-currency report delta", test_multi_currency_report_delta)
    _record("rollup CSV header and rows", test_rollup_csv_header_and_rows)
    _record("CLI report --json keys", test_cli_report_json_keys)
    _record("recent per-project summary", test_recent_per_project_summary)
    _record("doctor monthly review tip", test_doctor_monthly_review_tip)
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
