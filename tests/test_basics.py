"""
test_basics.py — Sprint 6: smoke tests covering DB, models, repository, metrics.

Runs against a temp DB. No pytest required — stdlib only.

Execute: PYTHONPATH=src python3 tests/test_basics.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone, timedelta

# Make src importable without `pip install -e .`
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from asset_tracker import db, models, repository, metrics


def _connect(db_path):
    """Helper that accepts a string path (Path | str)."""
    from pathlib import Path
    return db.connect(Path(db_path))


PASSED = 0
FAILED = 0
ERRORS = []


def fresh_db():
    td = tempfile.TemporaryDirectory()
    db_path = os.path.join(td.name, "test.db")
    conn = _connect(db_path)
    db.init_schema(conn)
    return td, conn


def seed_data(conn, days_offset: int = -10):
    """Insert one project, two channels, three transactions, one time log."""
    now = datetime.now(timezone.utc)
    project = models.Project(
        id="test-proj", name="Test Project", category="software", status="active",
        started_at=(now + timedelta(days=days_offset)).isoformat(timespec="seconds"),
    )
    repository.create_project(conn, project)
    ch1 = models.IncomeChannel(
        id=None, project_id="test-proj", name="Gumroad MRR",
        platform="gumroad", kind="recurring", fee_pct=0.10,
    )
    ch2 = models.IncomeChannel(
        id=None, project_id="test-proj", name="Direct tip",
        platform="direct", kind="tip",
    )
    cid1 = repository.create_channel(conn, ch1)
    cid2 = repository.create_channel(conn, ch2)
    repository.create_transaction(conn, models.Transaction(
        id=None, project_id="test-proj", channel_id=cid1, occurred_at=now.isoformat(timespec="seconds"),
        gross_amount=100.0, currency="USD", net_amount=100.0, kind="recurring",
    ))
    repository.create_transaction(conn, models.Transaction(
        id=None, project_id="test-proj", channel_id=cid1, occurred_at=now.isoformat(timespec="seconds"),
        gross_amount=50.0, currency="USD", net_amount=50.0, kind="recurring",
    ))
    repository.create_transaction(conn, models.Transaction(
        id=None, project_id="test-proj", channel_id=cid2, occurred_at=now.isoformat(timespec="seconds"),
        gross_amount=20.0, currency="USD", net_amount=20.0, kind="tip",
    ))
    repository.create_time_log(conn, models.TimeLog(
        id=None, project_id="test-proj",
        started_at=now.isoformat(timespec="seconds"),
        ended_at=(now + timedelta(hours=5)).isoformat(timespec="seconds"),
        minutes=300,
    ))
    return cid1, cid2


def _record_test(name, fn):
    """Execute a test function, capture pass/fail, increment counters."""
    global PASSED, FAILED
    try:
        fn()
        PASSED += 1
        print(f"  PASS  {name}")
    except AssertionError as e:
        FAILED += 1
        ERRORS.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")
    except Exception:
        FAILED += 1
        ERRORS.append((name, traceback.format_exc()))
        print(f"  ERROR {name}")
        traceback.print_exc()


# Each test is wrapped in a closure so the decorator can run it on definition.
def make_test(name):
    def wrap(fn):
        def runner():
            _record_test(name, fn)
        runner()
        return runner
    return wrap


# ---------- tests ----------

@make_test("db.connect creates file + enables FK")
def t01():
    td, conn = fresh_db()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.integrity_check(conn) == "ok"
    finally:
        conn.close(); td.cleanup()


@make_test("schema loads with all expected tables")
def t02():
    td, conn = fresh_db()
    try:
        tables = set(db.list_tables(conn))
        for required in {"projects", "income_channels", "transactions", "time_logs", "schema_meta"}:
            assert required in tables, f"missing table {required}"
    finally:
        conn.close(); td.cleanup()


@make_test("Project validation rejects bad category/status")
def t03():
    p = models.Project(id="x", name="X", category="INVALID", status="active")
    assert "category" in " ".join(p.validate())
    p2 = models.Project(id="x", name="X", category="software", status="WHAT")
    assert "status" in " ".join(p2.validate())


@make_test("Channel.fee_pct=10 + $100 gross → $10 fee, $90 net on insert")
def t04():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="software", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c", platform="gumroad",
                                   kind="recurring", fee_pct=0.10)
        cid = repository.create_channel(conn, ch)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tx = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=now, gross_amount=100.0, currency="USD",
                                 net_amount=100.0, kind="recurring")
        repository.create_transaction(conn, tx)
        assert tx.fee_amount == 10.0, f"expected 10.0 got {tx.fee_amount}"
        assert tx.net_amount == 90.0, f"expected 90.0 got {tx.net_amount}"
    finally:
        conn.close(); td.cleanup()


@make_test("Idempotent tx on (channel_id, external_id)")
def t05():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="software", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c", platform="stripe",
                                   kind="one_time")
        cid = repository.create_channel(conn, ch)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t1 = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=now, gross_amount=10.0, currency="USD",
                                 net_amount=10.0, kind="one_time", external_id="evt_X")
        id1 = repository.create_transaction(conn, t1)
        t2 = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=now, gross_amount=10.0, currency="USD",
                                 net_amount=10.0, kind="one_time", external_id="evt_X")
        id2 = repository.create_transaction(conn, t2)
        assert id1 != 0, "first insert should succeed"
        assert id2 == 0, f"duplicate insert should return 0, got {id2}"
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert count == 1, f"should have exactly 1 tx, got {count}"
    finally:
        conn.close(); td.cleanup()


@make_test("FK CASCADE: delete project removes channels + txns")
def t06():
    td, conn = fresh_db()
    try:
        seed_data(conn)
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM income_channels").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 3
        repository.delete_project(conn, "test-proj")
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM income_channels").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    finally:
        conn.close(); td.cleanup()


@make_test("metrics: MRR / ARR / YTD / total")
def t07():
    td, conn = fresh_db()
    try:
        seed_data(conn)
        m = metrics.compute_metrics(conn, period="all")
        assert m["mrr"] == 135.0, f"MRR expected 135.0 got {m['mrr']}"
        assert m["arr"] == 1620.0
        assert m["ytd_net"] == 155.0, f"YTD net expected 155.0 got {m['ytd_net']}"
        assert m["total_net"] == 155.0
        assert m["period_fees"] == 15.0, f"fees expected 15.0 got {m['period_fees']}"
    finally:
        conn.close(); td.cleanup()


@make_test("metrics: per-project ROI = net / hours")
def t08():
    td, conn = fresh_db()
    try:
        seed_data(conn)
        m = metrics.compute_metrics(conn, period="all")
        proj = m["per_project"][0]
        assert proj["net"] == 155.0
        assert proj["minutes"] == 300
        assert proj["hours"] == 5.0
        assert proj["revenue_per_hour"] == 31.0, f"ROI expected 31.0 got {proj['revenue_per_hour']}"
    finally:
        conn.close(); td.cleanup()


@make_test("metrics: per-platform grouping")
def t09():
    td, conn = fresh_db()
    try:
        seed_data(conn)
        m = metrics.compute_metrics(conn, period="all")
        platforms = {p["platform"]: p for p in m["per_platform"]}
        assert "gumroad" in platforms
        assert "direct" in platforms
        assert platforms["gumroad"]["net"] == 135.0
        assert platforms["gumroad"]["fees"] == 15.0
        assert platforms["gumroad"]["tx_count"] == 2
        assert platforms["direct"]["net"] == 20.0
        assert platforms["direct"]["fees"] == 0.0
    finally:
        conn.close(); td.cleanup()


@make_test("Transaction validation: refund must have net <= 0")
def t10():
    t = models.Transaction(id=None, project_id="x", channel_id=1,
                            occurred_at="2026-01-01T00:00:00+00:00",
                            gross_amount=10.0, currency="USD", net_amount=10.0, kind="refund")
    assert any("refund" in e for e in t.validate())
    t2 = models.Transaction(id=None, project_id="x", channel_id=1,
                             occurred_at="2026-01-01T00:00:00+00:00",
                             gross_amount=10.0, currency="USD", net_amount=-1.0, kind="one_time")
    assert any("non-refund" in e for e in t2.validate())


if __name__ == "__main__":
    print()
    print(f"=== {PASSED} passed, {FAILED} failed ===")
    if FAILED:
        print("\nFailures:")
        for name, err in ERRORS:
            print(f"  {name}: {err}")
        sys.exit(1)
    sys.exit(0)
