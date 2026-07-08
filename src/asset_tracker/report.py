"""
report.py — Wave 3: period comparisons and review summaries.

Builds human-readable and JSON reports from metrics windows.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from . import metrics as metrics_mod
from .dashboard import _box, _money, bold, cyan, dim, green, red, yellow, _term_width


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _delta(current: float, prior: float) -> dict[str, Any]:
    abs_delta = round(current - prior, 2)
    if prior == 0:
        # No meaningful percent when prior window is empty.
        pct = None
        label = "new" if current != 0 else "n/a"
    else:
        pct = round((abs_delta / prior) * 100, 1)
        label = None
    return {"absolute": abs_delta, "percent": pct, "label": label}


def _format_delta(d: dict[str, Any]) -> str:
    if d.get("label"):
        return d["label"]
    pct = d.get("percent")
    if pct is None:
        return "n/a"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def _sparkline(trend: list[dict], points: int = 14) -> str:
    if not trend:
        return dim("(no activity)")
    slice_ = trend[-points:]
    values = [row["net"] for row in slice_]
    max_v = max(values) if values else 0
    if max_v <= 0:
        return dim("▁" * len(slice_))
    out = []
    for v in values:
        if v <= 0:
            out.append(_SPARK_CHARS[0])
        else:
            idx = min(len(_SPARK_CHARS) - 1, int(round((v / max_v) * (len(_SPARK_CHARS) - 1))))
            out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _currency_comparison(current: dict, prior: Optional[dict]) -> list[dict]:
    cur_map = {r["currency"]: r for r in current.get("by_currency", [])}
    pri_map = {r["currency"]: r for r in (prior or {}).get("by_currency", [])}
    currencies = sorted(set(cur_map) | set(pri_map))
    rows = []
    for currency in currencies:
        c = cur_map.get(currency, {})
        p = pri_map.get(currency, {})
        c_net = c.get("period_net", 0.0)
        p_net = p.get("period_net", 0.0)
        rows.append({
            "currency": currency,
            "current_period_net": c_net,
            "prior_period_net": p_net,
            "delta": _delta(c_net, p_net),
        })
    return rows


def summarize_window(
    conn: sqlite3.Connection,
    since_iso: str,
    until_iso: str,
    project_id: Optional[str] = None,
) -> list[dict]:
    """Per-project net + tx count for a window (used by recent and report)."""
    sql = (
        "SELECT project_id, currency, "
        "       COALESCE(SUM(net_amount), 0) AS net, COUNT(*) AS tx_count "
        "FROM transactions "
        "WHERE occurred_at >= ? AND occurred_at <= ? "
    )
    args: list = [since_iso, until_iso]
    if project_id:
        sql += " AND project_id = ?"
        args.append(project_id)
    sql += " GROUP BY project_id, currency ORDER BY net DESC"
    return [
        {
            "project_id": r["project_id"],
            "currency": r["currency"],
            "net": round(r["net"] or 0, 2),
            "tx_count": r["tx_count"],
        }
        for r in conn.execute(sql, args).fetchall()
    ]


def build_report(
    conn: sqlite3.Connection,
    period: str = "30d",
    compare: bool = True,
    project_id: Optional[str] = None,
) -> dict:
    if period not in metrics_mod.VALID_PERIODS:
        raise ValueError(f"unknown period: {period}")
    if period == "all" and compare:
        compare = False

    start, end = metrics_mod._period_window(period)
    current = metrics_mod.compute_metrics_for_window(
        conn,
        start.isoformat(timespec="seconds"),
        end.isoformat(timespec="seconds"),
        project_id=project_id,
        period=period,
    )

    prior = None
    delta: dict[str, dict] = {}
    if compare:
        p_start, p_end = metrics_mod.prior_period_window(period)
        prior = metrics_mod.compute_metrics_for_window(
            conn,
            p_start.isoformat(timespec="seconds"),
            p_end.isoformat(timespec="seconds"),
            project_id=project_id,
            period=f"prior_{period}",
        )
        for key in ("period_net", "period_fees", "mrr", "tx_count", "hours_logged"):
            delta[key] = _delta(current.get(key, 0), prior.get(key, 0))

    highlights = {
        "projects": [
            {"id": p["id"], "name": p["name"], "net": p["net"]}
            for p in current.get("per_project", [])[:3]
            if p.get("net", 0) != 0
        ],
        "platforms": [
            {"platform": p["platform"], "net": p["net"], "tx_count": p["tx_count"]}
            for p in current.get("per_platform", [])[:3]
            if p.get("net", 0) != 0
        ],
    }

    return {
        "period": period,
        "compare": compare,
        "current": current,
        "prior": prior,
        "delta": delta,
        "highlights": highlights,
        "sparkline": _sparkline(current.get("trend", [])),
        "by_currency": _currency_comparison(current, prior),
    }


def format_report(report: dict) -> str:
    """Render a TUI report consistent with the dashboard style."""
    current = report["current"]
    period = report.get("period", "30d").upper()
    width = min(max(_term_width(), 80), 140)
    sections: list[str] = []

    title = bold(cyan("  asset-tracker report ")) + dim(
        f"· {current.get('window_start', '?')[:10]} → {current.get('window_end', '?')[:10]}"
    )
    sections.append(title)
    sections.append("")

    summary_lines = [
        f" {bold('Period:')} {cyan(period)}",
        "",
    ]
    by_curr = current.get("by_currency", [])
    if len(by_curr) <= 1:
        currency = by_curr[0]["currency"] if by_curr else "USD"
        net = current.get("period_net", 0.0)
        fees = current.get("period_fees", 0.0)
        mrr = current.get("mrr", 0.0)
        summary_lines.extend([
            f"  {bold('Net')}      {green(_money(net, currency)):>16}",
            f"  {bold('Fees')}     {red(_money(fees, currency)):>16}",
            f"  {bold('MRR')}      {_money(mrr, currency):>16}",
            f"  {bold('Txns')}     {current.get('tx_count', 0):>16}",
            f"  {bold('Hours')}    {current.get('hours_logged', 0):>16.1f}",
        ])
    else:
        summary_lines.append(f"  {'Currency':<8} {'Net':>14} {'Fees':>14} {'Txns':>8}")
        summary_lines.append("  " + "─" * (width - 4))
        for row in by_curr:
            summary_lines.append(
                f"  {row['currency']:<8} {green(_money(row['period_net'], row['currency'])):>14} "
                f"{red(_money(current.get('period_fees', 0), row['currency'])):>14} "
                f"{current.get('tx_count', 0):>8}"
            )

    if report.get("compare") and report.get("delta"):
        summary_lines.append("")
        summary_lines.append(f"  {bold('vs prior ' + period.lower())}")
        d = report["delta"]
        for label, key in (
            ("Net", "period_net"),
            ("Fees", "period_fees"),
            ("MRR", "mrr"),
            ("Txns", "tx_count"),
            ("Hours", "hours_logged"),
        ):
            delta = d.get(key, {})
            color = green if (delta.get("absolute") or 0) >= 0 else red
            if key == "period_fees":
                color = red if (delta.get("absolute") or 0) > 0 else green
            abs_v = delta.get("absolute", 0)
            if key == "tx_count":
                abs_str = f"({abs_v:+.0f})"
            elif key == "hours_logged":
                abs_str = f"({abs_v:+.1f}h)"
            else:
                abs_str = f"({abs_v:+.2f})"
            summary_lines.append(
                f"  {label:<8} {color(_format_delta(delta)):>10}  {dim(abs_str)}"
            )

    summary_lines.append("")
    summary_lines.append(f"  {bold('Trend')}  {report.get('sparkline', '')}")
    sections.extend(_box("Summary", summary_lines, width))
    sections.append("")

    proj_lines = []
    for p in report.get("highlights", {}).get("projects", []):
        proj_lines.append(f"  {p['id'][:28]:<28} {green(_money(p['net'])):>14}")
    if not proj_lines:
        proj_lines = ["  " + dim("(no project revenue in period)")]
    sections.extend(_box("Top projects", proj_lines, width))
    sections.append("")

    plat_lines = []
    for p in report.get("highlights", {}).get("platforms", []):
        plat_lines.append(
            f"  {p['platform']:<18} {green(_money(p['net'])):>14}  {p['tx_count']:>4} txns"
        )
    if not plat_lines:
        plat_lines = ["  " + dim("(no platform revenue in period)")]
    sections.extend(_box("Top platforms", plat_lines, width))

    return "\n".join(sections)
