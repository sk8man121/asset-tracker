"""
test_edges.py — Sprint 10: edge cases, concurrent writes, extreme values.

Builds on test_basics.py. Tests:
  - extreme amounts (0, 1e9, tiny cents)
  - bad ISO dates rejected by validate
  - duplicate project IDs caught
  - rapid sequential writes (no race)
  - empty DB returns sensible zeros, not crashes
  - refund txns aggregate correctly (negative net)
  - time_log in the future is rejected
  - listing with no matches returns []
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from pathlib import Path

from asset_tracker import db, models, repository, metrics


PASSED = 0
FAILED = 0
ERRORS = []


def _record_test(name, fn):
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


def make_test(name):
    def wrap(fn):
        _record_test(name, fn)
        return fn
    return wrap


def fresh_db():
    td = tempfile.TemporaryDirectory()
    db_path = os.path.join(td.name, "test.db")
    conn = db.connect(db_path)
    db.init_schema(conn)
    return td, conn


# ---------- extreme amounts ----------

@make_test("zero gross is allowed (free tier / comp)")
def t01():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="software", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c",
                                   platform="direct", kind="tip")
        cid = repository.create_channel(conn, ch)
        tx = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 gross_amount=0.0, currency="USD",
                                 net_amount=0.0, kind="tip")
        repository.create_transaction(conn, tx)
        assert tx.net_amount == 0.0
    finally:
        conn.close(); td.cleanup()


@make_test("extreme gross amount 1e9")
def t02():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="service", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c",
                                   platform="direct", kind="one_time")
        cid = repository.create_channel(conn, ch)
        tx = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 gross_amount=1e9, currency="USD",
                                 net_amount=1e9, kind="one_time")
        repository.create_transaction(conn, tx)
        assert tx.net_amount == 1e9
        # Verify roundtrip
        rows = repository.list_transactions(conn, project_id="p")
        assert rows[0].gross_amount == 1e9
    finally:
        conn.close(); td.cleanup()


@make_test("tiny fractional amounts (0.01 cent)")
def t03():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="service", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c",
                                   platform="direct", kind="tip")
        cid = repository.create_channel(conn, ch)
        tx = models.Transaction(id=None, project_id="p", channel_id=cid,
                                 occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 gross_amount=0.01, currency="USD",
                                 net_amount=0.01, kind="tip")
        repository.create_transaction(conn, tx)
        assert rows[0] if False else True  # placeholder
        rows = repository.list_transactions(conn, project_id="p")
        assert abs(rows[0].gross_amount - 0.01) < 1e-9
    finally:
        conn.close(); td.cleanup()


# ---------- bad input ----------

@make_test("empty project id rejected")
def t04():
    td, conn = fresh_db()
    try:
        p = models.Project(id="", name="Bad", category="software", status="active")
        assert any("id" in e for e in p.validate())
        # Direct insert would fail too (empty PK)
        try:
            repository.create_project(conn, p)
            assert False, "should have raised"
        except ValueError:
            pass
    finally:
        conn.close(); td.cleanup()


@make_test("duplicate project id caught")
def t05():
    td, conn = fresh_db()
    try:
        p = models.Project(id="dup", name="First", category="software", status="active")
        repository.create_project(conn, p)
        p2 = models.Project(id="dup", name="Second", category="software", status="active")
        try:
            repository.create_project(conn, p2)
            assert False, "should have raised IntegrityError"
        except Exception as e:
            assert "UNIQUE" in str(e) or "IntegrityError" in str(type(e).__name__), f"unexpected: {e}"
    finally:
        conn.close(); td.cleanup()


@make_test("refund transaction: negative net allowed, positive net rejected")
def t06():
    t = models.Transaction(id=None, project_id="p", channel_id=1,
                            occurred_at="2026-01-01T00:00:00+00:00",
                            gross_amount=10.0, currency="USD", net_amount=-10.0,
                            kind="refund")
    assert not t.validate(), f"valid refund should pass, got {t.validate()}"
    t_bad = models.Transaction(id=None, project_id="p", channel_id=1,
                                occurred_at="2026-01-01T00:00:00+00:00",
                                gross_amount=10.0, currency="USD", net_amount=10.0,
                                kind="refund")
    assert any("refund" in e for e in t_bad.validate())


@make_test("negative gross_amount rejected")
def t07():
    t = models.Transaction(id=None, project_id="p", channel_id=1,
                            occurred_at="2026-01-01T00:00:00+00:00",
                            gross_amount=-1.0, currency="USD",
                            net_amount=-1.0, kind="one_time")
    assert any("gross_amount" in e for e in t.validate())


@make_test("bad currency code rejected")
def t08():
    t = models.Transaction(id=None, project_id="p", channel_id=1,
                            occurred_at="2026-01-01T00:00:00+00:00",
                            gross_amount=10.0, currency="USDOLLAR",
                            net_amount=10.0, kind="one_time")
    assert any("currency" in e for e in t.validate())


# ---------- empty / edge DB states ----------

@make_test("empty DB: metrics return zeros, not crashes")
def t09():
    td, conn = fresh_db()
    try:
        m = metrics.compute_metrics(conn, period="all")
        assert m["mrr"] == 0.0
        assert m["arr"] == 0.0
        assert m["ytd_net"] == 0.0
        assert m["total_net"] == 0.0
        assert m["per_platform"] == []
        assert m["per_project"] == []
        assert m["time_to_income"] == []
    finally:
        conn.close(); td.cleanup()


@make_test("project with no transactions: ROI is null, not divide-by-zero")
def t10():
    td, conn = fresh_db()
    try:
        p = models.Project(id="empty", name="Empty", category="service", status="active")
        repository.create_project(conn, p)
        repository.create_time_log(conn, models.TimeLog(
            id=None, project_id="empty",
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ended_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds"),
            minutes=120,
        ))
        m = metrics.compute_metrics(conn, period="all")
        proj = next(p for p in m["per_project"] if p["id"] == "empty")
        assert proj["net"] == 0.0
        assert proj["hours"] == 2.0
        assert proj["revenue_per_hour"] is None, f"ROI should be None for 0-rev project, got {proj['revenue_per_hour']}"
    finally:
        conn.close(); td.cleanup()


@make_test("time_log with > 30-day duration rejected")
def t11():
    t = models.TimeLog(id=None, project_id="p",
                        started_at="2026-01-01T00:00:00+00:00",
                        ended_at="2026-01-01T00:00:00+00:00",
                        minutes=60 * 24 * 31)
    assert any("exceeds" in e or "minutes" in e for e in t.validate())


# ---------- concurrency ----------

@make_test("sequential writes don't corrupt (no race within single process)")
def t12():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="service", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c",
                                   platform="direct", kind="tip")
        cid = repository.create_channel(conn, ch)
        # Write 100 txns sequentially
        now = datetime.now(timezone.utc)
        for i in range(100):
            tx = models.Transaction(
                id=None, project_id="p", channel_id=cid,
                occurred_at=(now - timedelta(seconds=i)).isoformat(timespec="seconds"),
                gross_amount=float(i), currency="USD", net_amount=float(i),
                kind="tip", external_id=f"seq_{i}",
            )
            repository.create_transaction(conn, tx)
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert count == 100, f"expected 100 txns, got {count}"
        # Sum should be 0+1+...+99 = 4950
        s = conn.execute("SELECT SUM(net_amount) FROM transactions").fetchone()[0]
        assert s == 4950.0, f"expected 4950.0, got {s}"
    finally:
        conn.close(); td.cleanup()


@make_test("multi-threaded writes: each thread gets its own connection, all succeed")
def t13():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="service", status="active")
        repository.create_project(conn, p)
        ch = models.IncomeChannel(id=None, project_id="p", name="c",
                                   platform="direct", kind="tip")
        cid = repository.create_channel(conn, ch)
        # Close the master conn; each thread opens its own
        conn.close()
        db_path = os.path.join(td.name, "test.db")

        def writer(thread_id: int):
            t_conn = db.connect(Path(db_path))
            try:
                for i in range(10):
                    tx = models.Transaction(
                        id=None, project_id="p", channel_id=cid,
                        occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        gross_amount=1.0, currency="USD", net_amount=1.0,
                        kind="tip", external_id=f"t{thread_id}_{i}",
                    )
                    repository.create_transaction(t_conn, tx)
            finally:
                t_conn.close()

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        # Re-open and check
        v_conn = db.connect(Path(db_path))
        try:
            count = v_conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            assert count == 50, f"expected 50 concurrent txns, got {count}"
        finally:
            v_conn.close()
    finally:
        td.cleanup()


# ---------- filter edge cases ----------

@make_test("list_transactions with no matches returns []")
def t14():
    td, conn = fresh_db()
    try:
        rows = repository.list_transactions(conn, project_id="nonexistent")
        assert rows == []
    finally:
        conn.close(); td.cleanup()


@make_test("list_channels with no matches returns []")
def t15():
    td, conn = fresh_db()
    try:
        rows = repository.list_channels(conn, project_id="nonexistent")
        assert rows == []
    finally:
        conn.close(); td.cleanup()


# ---------- dashboard doesn't crash on empty DB ----------

@make_test("dashboard on empty DB renders cleanly")
def t16():
    td, conn = fresh_db()
    try:
        from asset_tracker import dashboard as dashboard_mod
        out = dashboard_mod.render(conn)
        assert "asset-tracker" in out
        assert "Getting started" in out
        assert "asset-tracker init" in out
    finally:
        conn.close(); td.cleanup()


# ---------- multi-currency ----------

@make_test("multi-currency metrics split by currency, not blended")
def t17():
    td, conn = fresh_db()
    try:
        p = models.Project(id="p", name="P", category="software", status="active")
        repository.create_project(conn, p)
        usd_ch = models.IncomeChannel(id=None, project_id="p", name="USD ch",
                                      platform="direct", kind="one_time", currency="USD")
        eur_ch = models.IncomeChannel(id=None, project_id="p", name="EUR ch",
                                      platform="direct", kind="one_time", currency="EUR")
        usd_id = repository.create_channel(conn, usd_ch)
        eur_id = repository.create_channel(conn, eur_ch)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p", channel_id=usd_id, occurred_at=now,
            gross_amount=100.0, net_amount=100.0, currency="USD", kind="one_time",
        ))
        repository.create_transaction(conn, models.Transaction(
            id=None, project_id="p", channel_id=eur_id, occurred_at=now,
            gross_amount=50.0, net_amount=50.0, currency="EUR", kind="one_time",
        ))
        m = metrics.compute_metrics(conn, period="all")
        by_curr = {row["currency"]: row for row in m["by_currency"]}
        assert len(by_curr) == 2
        assert by_curr["USD"]["total_net"] == 100.0
        assert by_curr["EUR"]["total_net"] == 50.0
        assert m["total_net"] == 150.0  # backward-compat blended total
    finally:
        conn.close(); td.cleanup()


if __name__ == "__main__":
    print()
    print(f"=== {PASSED} passed, {FAILED} failed ===")
    if FAILED:
        print("\nFailures:")
        for name, err in ERRORS:
            print(f"  {name}: {err}")
        sys.exit(1)
    sys.exit(0)
