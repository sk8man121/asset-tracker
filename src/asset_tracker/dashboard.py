"""
dashboard.py — Sprint 8: TUI dashboard.

Pure stdlib text-based dashboard using box-drawing characters.
Renders:
  - Top metrics panel: MRR / ARR / YTD / Total + Period fees
  - Per-platform breakdown
  - Per-project list with status, revenue, ROI
  - Active channels summary
  - Recent transactions (last 5)

ANSI color codes supported (auto-disabled if NO_COLOR env set).
Width adapts to terminal (default 100 cols).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional


# ---- ANSI codes ----

_USE_COLOR = os.environ.get("NO_COLOR") is None and os.environ.get("AT_NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)
def magenta(t): return _c("35", t)
def blue(t): return _c("34", t)


# ---- box-drawing ----

def _term_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size().columns or default
    except (OSError, ValueError):
        return default


def _box(title: str, lines: list[str], width: int = 100) -> list[str]:
    """Render a titled box. Returns a list of lines (each stripped to width)."""
    inner = width - 2
    bar = "─" * inner
    out = []
    if title:
        tlen = len(title)
        left = max(1, (inner - tlen - 2) // 2)
        right = max(1, inner - tlen - 2 - left)
        out.append("┌" + "─" * left + f" {title} " + "─" * right + "┐")
    else:
        out.append("┌" + bar + "┐")
    for line in lines:
        # Truncate visible chars (ignore ANSI when measuring). Cheap: assume ≤ 2x width.
        vlen = len(line)
        if vlen > inner:
            line = line[: inner - 1] + "…"
            vlen = inner
        pad = inner - vlen
        out.append("│" + line + " " * pad + "│")
    out.append("└" + bar + "┘")
    return out


def _money(n: float, currency: str = "USD") -> str:
    return f"{currency} {n:,.2f}"


def _bar(value: float, max_value: float, width: int = 20) -> str:
    if max_value <= 0:
        return " " * width
    filled = max(0, min(width, int(round((value / max_value) * width))))
    return "█" * filled + "·" * (width - filled)


# ---- renderers ----

def _top_metrics(m: dict, width: int) -> list[str]:
    period = m.get("period", "30d").upper()
    mrr = m.get("mrr", 0.0)
    arr = m.get("arr", 0.0)
    ytd = m.get("ytd_net", 0.0)
    total = m.get("total_net", 0.0)
    fees = m.get("period_fees", 0.0)
    p_net = m.get("period_net", 0.0)
    return [
        f" {bold('Period:')} {cyan(period)}            "
        f"{bold('Window:')} {m.get('window_start', '?')[:10]} → {m.get('window_end', '?')[:10]}",
        "",
        f"  {bold('MRR')}   {_money(mrr):>14}    "
        f"{bold('ARR')}   {_money(arr):>14}    "
        f"{bold('Fees')}   {red(_money(fees)):>14}",
        f"  {bold('YTD')}   {green(_money(ytd)):>14}    "
        f"{bold('Total')} {green(_money(total)):>14}    "
        f"{bold(f'{period} net')}   {green(_money(p_net)):>14}",
    ]


def _platform_table(m: dict, width: int) -> list[str]:
    plats = m.get("per_platform", [])
    if not plats:
        return ["  " + dim("(no platforms in period)")]
    header = f"  {'Platform':<18} {'Net':>14} {'Fees':>10} {'Tx':>5}  Bar"
    lines = [header, "  " + "─" * (width - 4)]
    max_net = max((p["net"] for p in plats), default=0) or 1
    for p in plats:
        bar = _bar(p["net"], max_net, width=24)
        net_color = green if p["net"] >= 0 else red
        lines.append(
            f"  {p['platform']:<18} {net_color(_money(p['net'])):>14} "
            f"{_money(p['fees']):>10} {p['tx_count']:>5}  {bar}"
        )
    return lines


def _project_table(m: dict, width: int) -> list[str]:
    projs = m.get("per_project", [])
    if not projs:
        return ["  " + dim("(no projects)")]
    header = f"  {'Project':<28} {'Cat':<10} {'Status':<8} {'Net':>12} {'$/hr':>8} {'Hours':>6}"
    lines = [header, "  " + "─" * (width - 4)]
    for p in projs:
        status_color = {
            "active": green, "dormant": yellow, "archived": dim, "idea": cyan
        }.get(p["status"], dim)
        roi = p.get("revenue_per_hour")
        roi_str = f"{roi:>8.2f}" if roi is not None else "       —"
        net_color = green if p["net"] >= 0 else red
        lines.append(
            f"  {p['id'][:28]:<28} {p['category'][:10]:<10} "
            f"{status_color(p['status']):<8} {net_color(_money(p['net'])):>12} "
            f"{roi_str} {p['hours']:>6.1f}"
        )
    return lines


def _channels_panel(conn: sqlite3.Connection, width: int) -> list[str]:
    from . import repository
    channels = repository.list_channels(conn, active_only=True)
    if not channels:
        return ["  " + dim("(no active channels)")]
    header = f"  {'#':>3}  {'Project':<24} {'Platform':<14} {'Kind':<10} {'Name':<22} Fee"
    lines = [header, "  " + "─" * (width - 4)]
    for c in channels[:12]:  # cap at 12 to keep dashboard scannable
        fee_str = ""
        if c.fee_pct:
            fee_str += f"{c.fee_pct*100:.1f}%"
        if c.fee_flat:
            fee_str += f"+{c.fee_flat:.2f}"
        if not fee_str:
            fee_str = "—"
        lines.append(
            f"  {c.id:>3}  {c.project_id[:24]:<24} {c.platform:<14} {c.kind:<10} "
            f"{c.name[:22]:<22} {dim(fee_str)}"
        )
    if len(channels) > 12:
        lines.append(f"  {dim(f'… and {len(channels)-12} more')}")
    return lines


def _recent_tx(conn: sqlite3.Connection, width: int, limit: int = 5) -> list[str]:
    from . import repository
    txs = repository.list_transactions(conn, limit=limit)
    if not txs:
        return ["  " + dim("(no transactions yet)")]
    header = f"  {'Date':<11} {'Project':<28} {'Kind':<10} {'Gross':>10} {'Fee':>8} {'Net':>10}"
    lines = [header, "  " + "─" * (width - 4)]
    for t in txs:
        lines.append(
            f"  {t.occurred_at[:10]:<11} {t.project_id[:28]:<28} {t.kind:<10} "
            f"{t.gross_amount:>10.2f} {t.fee_amount:>8.2f} {t.net_amount:>10.2f}"
        )
    return lines


def _tti_panel(m: dict, width: int) -> list[str]:
    tti = m.get("time_to_income", [])
    if not tti:
        return ["  " + dim("(no projects with first-income data)")]
    lines = []
    for r in sorted(tti, key=lambda x: x["days_to_first_income"])[:5]:
        days = r["days_to_first_income"]
        color = green if days < 90 else (yellow if days < 365 else dim)
        lines.append(f"  {r['name'][:32]:<32}  {color(f'{days} days')}")
    return lines


# ---- main entrypoint ----

def render(conn: sqlite3.Connection, period: str = "30d") -> str:
    """Build the full dashboard as a single string. Width adapts to terminal."""
    from . import metrics as metrics_mod
    from . import onboard
    m = metrics_mod.compute_metrics(conn, period=period)
    width = min(max(_term_width(), 80), 140)
    sections: list[str] = []
    title = bold(cyan("  asset-tracker ")) + dim(f"· {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    sections.append(title)
    sections.append("")

    if not onboard.is_initialized(conn):
        sections.extend(_box("Getting started", [
            "  Your registry is empty. Run one of:",
            "",
            "    asset-tracker init              # guided setup",
            "    asset-tracker init --seed       # demo data to explore",
            "",
            "  Then log income:",
            "    asset-tracker log 49.99",
        ], width))
        return "\n".join(sections)

    sections.extend(_box("Top metrics", _top_metrics(m, width), width))
    sections.append("")
    sections.extend(_box("By platform", _platform_table(m, width), width))
    sections.append("")
    sections.extend(_box("By project", _project_table(m, width), width))
    sections.append("")
    sections.extend(_box("Active income channels", _channels_panel(conn, width), width))
    sections.append("")
    sections.extend(_box("Recent transactions", _recent_tx(conn, width), width))
    sections.append("")
    sections.extend(_box("Time to first income", _tti_panel(m, width), width))
    return "\n".join(sections)
