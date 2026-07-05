"""
metrics.py — Sprint 5: calculation & analytics engine.

Computes:
  - MRR (Monthly Recurring Revenue): last 30 days of recurring-kind transactions
  - ARR: MRR × 12
  - YTD revenue: net since Jan 1 of current year
  - Total revenue: net all-time
  - Per-project: revenue, hours, ROI (revenue / hour), time-to-income
  - Per-platform: revenue + fees paid to each
  - Trend: daily net for the last `period` days

Pure stdlib. Period filter is a single SQL WHERE clause on `occurred_at`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from . import repository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _period_window(period: str) -> tuple[datetime, datetime]:
    """Return (start, end) datetime for a period string."""
    now = _now()
    if period == "30d":
        return now - timedelta(days=30), now
    if period == "90d":
        return now - timedelta(days=90), now
    if period == "ytd":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    if period == "all":
        # Effectively no lower bound; use a sentinel.
        return datetime(1970, 1, 1, tzinfo=timezone.utc), now
    raise ValueError(f"unknown period: {period}")


def _sum_query(
    conn: sqlite3.Connection,
    project_id: Optional[str],
    start_iso: str,
    end_iso: str,
    extra_where: str = "1=1",
    extra_args: tuple = (),
) -> tuple[float, float]:
    """Return (net_total, fee_total) for transactions in window. Refunds count as negative."""
    sql = (
        "SELECT COALESCE(SUM(net_amount), 0) AS net, "
        "       COALESCE(SUM(fee_amount), 0) AS fees "
        "FROM transactions "
        "WHERE occurred_at >= ? AND occurred_at <= ? "
    )
    args: list = [start_iso, end_iso]
    if project_id:
        sql += " AND project_id = ?"
        args.append(project_id)
    sql += f" AND {extra_where}"
    args.extend(extra_args)
    row = conn.execute(sql, args).fetchone()
    return (round(row["net"] or 0, 2), round(row["fees"] or 0, 2))


def compute_metrics(
    conn: sqlite3.Connection,
    project_id: Optional[str] = None,
    period: str = "30d",
) -> dict:
    start, end = _period_window(period)
    start_iso = start.isoformat(timespec="seconds")
    end_iso = end.isoformat(timespec="seconds")

    # MRR: last-30-days recurring-kind transactions, scoped by period if 30d, else still computed on last 30d
    mrr_start = (_now() - timedelta(days=30)).isoformat(timespec="seconds")
    mrr_net, _ = _sum_query(conn, project_id, mrr_start, end_iso,
                             extra_where="kind = 'recurring'")
    mrr_net = round(mrr_net, 2)

    # Period totals
    p_net, p_fees = _sum_query(conn, project_id, start_iso, end_iso)
    # YTD (always calendar year, regardless of period)
    ytd_start = _now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    ytd_net, ytd_fees = _sum_query(conn, project_id, ytd_start, end_iso)
    # All-time
    total_net, total_fees = _sum_query(conn, project_id, "1970-01-01T00:00:00+00:00", end_iso)

    # Per-platform breakdown (period-scoped, joined via income_channels)
    sql = (
        "SELECT c.platform AS platform, "
        "       COALESCE(SUM(t.net_amount), 0) AS net, "
        "       COALESCE(SUM(t.fee_amount), 0) AS fees, "
        "       COUNT(t.id) AS tx_count "
        "FROM transactions t JOIN income_channels c ON t.channel_id = c.id "
        "WHERE t.occurred_at >= ? AND t.occurred_at <= ? "
    )
    args: list = [start_iso, end_iso]
    if project_id:
        sql += " AND t.project_id = ?"
        args.append(project_id)
    sql += " GROUP BY c.platform ORDER BY net DESC"
    per_platform = [
        {"platform": r["platform"], "net": round(r["net"], 2),
         "fees": round(r["fees"], 2), "tx_count": r["tx_count"]}
        for r in conn.execute(sql, args).fetchall()
    ]

    # Per-project: revenue + time + ROI (for the requested scope).
    # NOTE: a naive LEFT JOIN with time_logs would multiply minutes by the number
    # of transactions for that project (cartesian product). Use scalar subqueries
    # to avoid that.
    proj_sql = (
        "SELECT p.id AS id, p.name AS name, p.category AS category, "
        "       p.status AS status, p.started_at AS started_at, "
        "       COALESCE((SELECT SUM(net_amount) FROM transactions t "
        "                 WHERE t.project_id = p.id "
        "                   AND t.occurred_at >= ? AND t.occurred_at <= ?), 0) AS net, "
        "       COALESCE((SELECT SUM(minutes) FROM time_logs tl "
        "                 WHERE tl.project_id = p.id), 0) AS minutes "
        "FROM projects p WHERE 1=1 "
    )
    proj_args: list = [start_iso, end_iso]
    if project_id:
        proj_sql += " AND p.id = ?"
        proj_args.append(project_id)
    proj_sql += " ORDER BY net DESC"

    per_project = []
    for r in conn.execute(proj_sql, proj_args).fetchall():
        hours = (r["minutes"] or 0) / 60.0
        net_v = round(r["net"] or 0, 2)
        # ROI is meaningful only when there's both revenue AND time invested.
        # Zero-revenue projects show None (would be infinite or misleading otherwise).
        if net_v > 0 and hours > 0:
            roi = round(net_v / hours, 2)
        else:
            roi = None
        per_project.append({
            "id": r["id"], "name": r["name"], "category": r["category"],
            "status": r["status"], "started_at": r["started_at"],
            "net": net_v, "minutes": r["minutes"] or 0, "hours": round(hours, 2),
            "revenue_per_hour": roi,
        })

    # Time-to-income per project (only projects that actually earned)
    tti_sql = (
        "SELECT p.id AS id, p.name AS name, p.started_at AS started_at, "
        "       MIN(t.occurred_at) AS first_income_at "
        "FROM projects p "
        "JOIN transactions t ON t.project_id = p.id AND t.net_amount > 0 "
        "WHERE p.started_at IS NOT NULL "
    )
    tti_args: list = []
    if project_id:
        tti_sql += " AND p.id = ?"
        tti_args.append(project_id)
    tti_sql += " GROUP BY p.id"
    time_to_income = []
    for r in conn.execute(tti_sql, tti_args).fetchall():
        try:
            s = datetime.fromisoformat(r["started_at"])
            f = datetime.fromisoformat(r["first_income_at"])
            days = (f - s).days
            time_to_income.append({"project_id": r["id"], "name": r["name"],
                                    "days_to_first_income": days})
        except (TypeError, ValueError):
            continue

    # Daily trend for period
    trend_sql = (
        "SELECT substr(occurred_at, 1, 10) AS day, "
        "       COALESCE(SUM(net_amount), 0) AS net, COUNT(*) AS tx_count "
        "FROM transactions WHERE occurred_at >= ? AND occurred_at <= ? "
    )
    trend_args: list = [start_iso, end_iso]
    if project_id:
        trend_sql += " AND project_id = ?"
        trend_args.append(project_id)
    trend_sql += " GROUP BY day ORDER BY day"
    trend = [{"day": r["day"], "net": round(r["net"], 2), "tx_count": r["tx_count"]}
             for r in conn.execute(trend_sql, trend_args).fetchall()]

    # Per-currency breakdown (no FX conversion — native amounts only)
    mrr_start_iso = (_now() - timedelta(days=30)).isoformat(timespec="seconds")
    curr_sql = (
        "SELECT currency, "
        "       COALESCE(SUM(CASE WHEN kind = 'recurring' AND occurred_at >= ? AND occurred_at <= ? "
        "                    THEN net_amount ELSE 0 END), 0) AS mrr, "
        "       COALESCE(SUM(CASE WHEN occurred_at >= ? AND occurred_at <= ? THEN net_amount ELSE 0 END), 0) AS period_net, "
        "       COALESCE(SUM(CASE WHEN occurred_at >= ? AND occurred_at <= ? THEN net_amount ELSE 0 END), 0) AS ytd_net, "
        "       COALESCE(SUM(net_amount), 0) AS total_net "
        "FROM transactions WHERE 1=1 "
    )
    curr_args: list = [mrr_start_iso, end_iso, start_iso, end_iso, ytd_start, end_iso]
    if project_id:
        curr_sql += " AND project_id = ?"
        curr_args.append(project_id)
    curr_sql += " GROUP BY currency ORDER BY total_net DESC"
    by_currency = [
        {
            "currency": r["currency"],
            "mrr": round(r["mrr"] or 0, 2),
            "arr": round((r["mrr"] or 0) * 12, 2),
            "period_net": round(r["period_net"] or 0, 2),
            "ytd_net": round(r["ytd_net"] or 0, 2),
            "total_net": round(r["total_net"] or 0, 2),
        }
        for r in conn.execute(curr_sql, curr_args).fetchall()
    ]

    return {
        "period": period,
        "window_start": start_iso,
        "window_end": end_iso,
        "mrr": mrr_net,
        "arr": round(mrr_net * 12, 2),
        "period_net": round(p_net, 2),
        "period_fees": round(p_fees, 2),
        "ytd_net": round(ytd_net, 2),
        "ytd_fees": round(ytd_fees, 2),
        "total_net": round(total_net, 2),
        "total_fees": round(total_fees, 2),
        "per_platform": per_platform,
        "per_project": per_project,
        "time_to_income": time_to_income,
        "trend": trend,
        "by_currency": by_currency,
    }
