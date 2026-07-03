"""
repository.py — CRUD over the SQLite schema. Thin layer on top of db.connect().

Each function takes a sqlite3.Connection. All inserts return the new row id (or
list of ids for bulk). All lookups return model dataclasses or None / [].
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from . import models


# ---------- helpers ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- projects ----------

def create_project(conn: sqlite3.Connection, p: models.Project) -> str:
    """Insert a project. Returns the project id (already on p)."""
    errs = p.validate()
    if errs:
        raise ValueError(f"invalid Project: {errs}")
    conn.execute(
        """
        INSERT INTO projects (id, name, category, status, created_at, description,
                              started_at, tech_stack, repo_url, repo_local_path,
                              time_to_first_income_days, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (p.id, p.name, p.category, p.status, p.created_at, p.description,
         p.started_at, p.tech_stack, p.repo_url, p.repo_local_path,
         p.time_to_first_income_days, p.notes),
    )
    conn.commit()
    return p.id


def get_project(conn: sqlite3.Connection, project_id: str) -> Optional[models.Project]:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return models.Project.from_row(row) if row else None


def list_projects(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    category: Optional[str] = None,
) -> list[models.Project]:
    sql = "SELECT * FROM projects WHERE 1=1"
    args: list = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if category:
        sql += " AND category=?"
        args.append(category)
    sql += " ORDER BY created_at DESC"
    return [models.Project.from_row(r) for r in conn.execute(sql, args).fetchall()]


def update_project(
    conn: sqlite3.Connection, project_id: str, fields: dict
) -> models.Project:
    """Patch any subset of mutable project fields. Whitelists column names."""
    allowed = {"name", "category", "status", "description", "started_at",
               "tech_stack", "repo_url", "repo_local_path",
               "time_to_first_income_days", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_project(conn, project_id)  # no-op
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [project_id]
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id=?", values)
    conn.commit()
    updated = get_project(conn, project_id)
    if updated is None:
        raise LookupError(f"project {project_id} not found after update")
    return updated


def delete_project(conn: sqlite3.Connection, project_id: str) -> bool:
    cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------- income channels ----------

def create_channel(conn: sqlite3.Connection, c: models.IncomeChannel) -> int:
    errs = c.validate()
    if errs:
        raise ValueError(f"invalid IncomeChannel: {errs}")
    cur = conn.execute(
        """
        INSERT INTO income_channels (project_id, name, platform, kind, currency,
                                     fee_pct, fee_flat, active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (c.project_id, c.name, c.platform, c.kind, c.currency,
         c.fee_pct, c.fee_flat, c.active, c.created_at),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_channels(
    conn: sqlite3.Connection, project_id: Optional[str] = None, active_only: bool = False
) -> list[models.IncomeChannel]:
    sql = "SELECT * FROM income_channels WHERE 1=1"
    args: list = []
    if project_id:
        sql += " AND project_id=?"
        args.append(project_id)
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY project_id, name"
    return [models.IncomeChannel.from_row(r) for r in conn.execute(sql, args).fetchall()]


def get_channel(conn: sqlite3.Connection, channel_id: int) -> Optional[models.IncomeChannel]:
    row = conn.execute("SELECT * FROM income_channels WHERE id=?", (channel_id,)).fetchone()
    return models.IncomeChannel.from_row(row) if row else None


def resolve_channel(
    conn: sqlite3.Connection,
    project_id: str,
    ref: str | int,
) -> models.IncomeChannel:
    """Resolve a channel by numeric id, exact name, partial name, or platform.

    Raises LookupError with a helpful message when ambiguous or missing.
    """
    ref_str = str(ref).strip()
    if ref_str.isdigit():
        ch = get_channel(conn, int(ref_str))
        if ch is None:
            raise LookupError(f"channel #{ref_str} not found")
        if ch.project_id != project_id:
            raise LookupError(
                f"channel #{ref_str} belongs to project '{ch.project_id}', not '{project_id}'"
            )
        return ch

    channels = list_channels(conn, project_id=project_id)
    if not channels:
        raise LookupError(
            f"no channels for project '{project_id}' — run: "
            f"asset-tracker channel add --project {project_id} ..."
        )

    needle = ref_str.lower()
    exact_name = [c for c in channels if c.name.lower() == needle]
    if len(exact_name) == 1:
        return exact_name[0]

    partial_name = [c for c in channels if needle in c.name.lower()]
    if len(partial_name) == 1:
        return partial_name[0]

    by_platform = [c for c in channels if c.platform.lower() == needle]
    if len(by_platform) == 1:
        return by_platform[0]

    if len(partial_name) > 1:
        names = ", ".join(f"'{c.name}'" for c in partial_name)
        raise LookupError(f"channel '{ref_str}' is ambiguous — matches: {names}")
    if len(by_platform) > 1:
        names = ", ".join(f"'{c.name}' (#{c.id})" for c in by_platform)
        raise LookupError(f"platform '{ref_str}' is ambiguous — channels: {names}")

    available = ", ".join(f"'{c.name}' (#{c.id})" for c in channels)
    raise LookupError(
        f"channel '{ref_str}' not found for project '{project_id}'. "
        f"Available: {available}"
    )


# ---------- transactions ----------

def create_transaction(conn: sqlite3.Connection, t: models.Transaction) -> int:
    """Insert a transaction. If fee_amount is 0 and the channel has fee rules,
    auto-compute. Idempotent on (channel_id, external_id)."""
    errs = t.validate()
    if errs:
        raise ValueError(f"invalid Transaction: {errs}")
    # Auto-fill fee_amount from channel rules if caller didn't set one.
    # external_id is for idempotency, NOT a fee-skip signal.
    if t.fee_amount == 0.0:
        ch = get_channel(conn, t.channel_id)
        if ch and (ch.fee_pct or ch.fee_flat):
            t.fee_amount = ch.compute_fee(t.gross_amount)
            t.net_amount = round(t.gross_amount - t.fee_amount, 2)
    try:
        cur = conn.execute(
            """
            INSERT INTO transactions (project_id, channel_id, occurred_at, gross_amount,
                                       currency, fee_amount, net_amount, kind,
                                       external_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (t.project_id, t.channel_id, t.occurred_at, t.gross_amount,
             t.currency, t.fee_amount, t.net_amount, t.kind,
             t.external_id, t.notes),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    except sqlite3.IntegrityError as e:
        # Idempotent re-import on same external_id
        if t.external_id and "UNIQUE" in str(e):
            return 0
        raise


def list_transactions(
    conn: sqlite3.Connection,
    project_id: Optional[str] = None,
    channel_id: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 1000,
) -> list[models.Transaction]:
    sql = "SELECT * FROM transactions WHERE 1=1"
    args: list = []
    if project_id:
        sql += " AND project_id=?"
        args.append(project_id)
    if channel_id:
        sql += " AND channel_id=?"
        args.append(channel_id)
    if since:
        sql += " AND occurred_at >= ?"
        args.append(since)
    if until:
        sql += " AND occurred_at <= ?"
        args.append(until)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    sql += " ORDER BY occurred_at DESC LIMIT ?"
    args.append(limit)
    return [models.Transaction.from_row(r) for r in conn.execute(sql, args).fetchall()]


# ---------- time logs ----------

def create_time_log(conn: sqlite3.Connection, t: models.TimeLog) -> int:
    errs = t.validate()
    if errs:
        raise ValueError(f"invalid TimeLog: {errs}")
    cur = conn.execute(
        "INSERT INTO time_logs (project_id, started_at, ended_at, minutes, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (t.project_id, t.started_at, t.ended_at, t.minutes, t.notes),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_time_logs(
    conn: sqlite3.Connection, project_id: Optional[str] = None
) -> list[models.TimeLog]:
    sql = "SELECT * FROM time_logs WHERE 1=1"
    args: list = []
    if project_id:
        sql += " AND project_id=?"
        args.append(project_id)
    sql += " ORDER BY started_at DESC"
    return [models.TimeLog.from_row(r) for r in conn.execute(sql, args).fetchall()]
