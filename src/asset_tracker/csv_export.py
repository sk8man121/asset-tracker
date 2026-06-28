"""
csv_export.py — Sprint 11: CSV export for cross-tool portability.

Pure stdlib. Writes to any file-like object (path string or sys.stdout).
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime
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
