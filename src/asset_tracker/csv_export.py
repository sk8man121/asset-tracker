"""
csv_export.py — Sprint 11: CSV export for cross-tool portability.

Pure stdlib. Writes to any file-like object (path string or sys.stdout).
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO

from . import repository


def export_transactions_csv(
    conn: sqlite3.Connection,
    out: TextIO | str | Path,
    project_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    kind: Optional[str] = None,
) -> int:
    """Write a filtered transaction list as CSV. Returns row count written."""
    txs = repository.list_transactions(
        conn, project_id=project_id, since=since, until=until, kind=kind, limit=10_000
    )
    own = False
    if isinstance(out, (str, Path)):
        own = True
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(out_path, "w", newline="")
    try:
        w = csv.writer(out)
        w.writerow([
            "id", "occurred_at", "project_id", "channel_id",
            "kind", "currency", "gross_amount", "fee_amount", "net_amount",
            "external_id", "notes",
        ])
        for t in txs:
            w.writerow([
                t.id, t.occurred_at, t.project_id, t.channel_id,
                t.kind, t.currency, t.gross_amount, t.fee_amount, t.net_amount,
                t.external_id or "", t.notes or "",
            ])
        return len(txs)
    finally:
        if own:
            out.close()


def export_projects_csv(
    conn: sqlite3.Connection,
    out: TextIO | str | Path,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> int:
    projs = repository.list_projects(conn, status=status, category=category)
    own = False
    if isinstance(out, (str, Path)):
        own = True
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(out_path, "w", newline="")
    try:
        w = csv.writer(out)
        w.writerow([
            "id", "name", "category", "status", "created_at", "started_at",
            "tech_stack", "repo_url", "repo_local_path",
            "time_to_first_income_days", "notes",
        ])
        for p in projs:
            w.writerow([
                p.id, p.name, p.category, p.status, p.created_at, p.started_at or "",
                p.tech_stack or "", p.repo_url or "", p.repo_local_path or "",
                p.time_to_first_income_days if p.time_to_first_income_days is not None else "",
                p.notes or "",
            ])
        return len(projs)
    finally:
        if own:
            out.close()


def export_rollup_csv(
    conn: sqlite3.Connection,
    out: TextIO | str | Path,
    year: Optional[int] = None,
) -> int:
    """Monthly rollup by project/platform/currency for tax-year spreadsheets."""
    yr = year or datetime.now(timezone.utc).year
    start_iso = f"{yr}-01-01T00:00:00+00:00"
    end_iso = f"{yr}-12-31T23:59:59+00:00"
    sql = (
        "SELECT substr(t.occurred_at, 1, 7) AS month, "
        "       t.project_id, c.platform, t.currency, "
        "       COALESCE(SUM(t.gross_amount), 0) AS gross, "
        "       COALESCE(SUM(t.fee_amount), 0) AS fees, "
        "       COALESCE(SUM(t.net_amount), 0) AS net, "
        "       COUNT(t.id) AS tx_count "
        "FROM transactions t "
        "JOIN income_channels c ON t.channel_id = c.id "
        "WHERE t.occurred_at >= ? AND t.occurred_at <= ? "
        "GROUP BY month, t.project_id, c.platform, t.currency "
        "ORDER BY month, t.project_id, c.platform, t.currency"
    )
    rows = conn.execute(sql, (start_iso, end_iso)).fetchall()
    own = False
    if isinstance(out, (str, Path)):
        own = True
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(out_path, "w", newline="")
    try:
        w = csv.writer(out)
        w.writerow(["month", "project_id", "platform", "currency", "gross", "fees", "net", "tx_count"])
        for r in rows:
            w.writerow([
                r["month"], r["project_id"], r["platform"], r["currency"],
                round(r["gross"] or 0, 2), round(r["fees"] or 0, 2),
                round(r["net"] or 0, 2), r["tx_count"],
            ])
        return len(rows)
    finally:
        if own:
            out.close()
