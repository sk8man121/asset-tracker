"""
integrations.py — Sprint 9: extensibility framework for external platforms.

Each platform gets a Connector class with a uniform interface:
  - is_configured() -> bool
  - fetch_recent() -> list[NormalizedTxn]
  - normalize(raw) -> NormalizedTxn
  - verify() -> tuple[bool, str]

Live HTTP calls are intentionally NOT made. The methods that *would* call a
remote API are gated behind `AT_LIVE_INTEGRATIONS=1` and raise NotImplementedError
otherwise. This is the scaffold for future live integrations.

To wire a new platform:
  1. Subclass `Connector`
  2. Implement `platform_id`, `platform_name`, `fetch_recent`, `normalize`
  3. Add it to `REGISTRY` below
  4. Set the matching env var to enable `is_configured()` -> True

The `NormalizedTxn` dataclass is the lingua franca — all platform-specific
shapes get converted to it before being written into the local DB.
"""
from __future__ import annotations

import os
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from . import http as http_mod


@dataclass
class NormalizedTxn:
    """Platform-agnostic transaction. All connectors return this shape."""
    external_id: str          # Platform's unique ID (idempotency key in our DB)
    project_id: str           # FK to local projects.id (mapping is platform-specific)
    channel_name: str         # Display name; matched against existing channels
    occurred_at: str          # ISO 8601 UTC
    gross_amount: float
    fee_amount: float = 0.0
    net_amount: Optional[float] = None  # If None, computed at insert time
    currency: str = "USD"
    kind: str = "one_time"    # recurring / one_time / royalty / tip / refund
    notes: Optional[str] = None

    def finalize_net(self) -> None:
        if self.net_amount is None:
            self.net_amount = round(self.gross_amount - self.fee_amount, 2)


# ---------- base ----------

class Connector:
    platform_id: str = "abstract"
    platform_name: str = "Abstract"
    env_var: str = ""          # e.g. "AT_STRIPE_API_KEY"

    def __init__(self) -> None:
        pass

    def _env_value(self) -> str:
        return os.environ.get(self.env_var, "")

    def is_configured(self) -> bool:
        return bool(self._env_value())

    def verify(self) -> tuple[bool, str]:
        """Return (ok, message). Override to ping remote API when configured."""
        if not self.is_configured():
            return (False, f"{self.env_var} not set")
        if os.environ.get("AT_LIVE_INTEGRATIONS") and hasattr(self, "_verify_live"):
            return self._verify_live()  # type: ignore[attr-defined]
        return (True, f"{self.env_var} present (length={len(self._env_value())})")

    def fetch_recent(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        """Override in subclasses. Default: raise unless LIVE_INTEGRATIONS enabled."""
        if not os.environ.get("AT_LIVE_INTEGRATIONS"):
            raise NotImplementedError(
                f"{self.platform_name} connector: live fetch_recent() requires "
                "AT_LIVE_INTEGRATIONS=1. This stub is read-only by design."
            )
        return self._fetch_recent_impl(since_iso, until_iso)

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        raise NotImplementedError

    def normalize(self, raw: dict) -> NormalizedTxn:
        raise NotImplementedError


# ---------- concrete connectors ----------

class StripeConnector(Connector):
    """Stripe: subscriptions, one-time payments, refunds."""
    platform_id = "stripe"
    platform_name = "Stripe"
    env_var = "AT_STRIPE_API_KEY"

    def _verify_live(self) -> tuple[bool, str]:
        try:
            data = http_mod.get_json(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {self._env_value()}"},
            )
            avail = data.get("available", [{}])[0]
            return (True, f"Stripe OK — {avail.get('currency', '?').upper()} available")
        except http_mod.HttpError as e:
            return (False, str(e))

    def _iso_to_unix(self, iso: str) -> int:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        since_unix = self._iso_to_unix(since_iso)
        until_unix = self._iso_to_unix(until_iso)
        charges: list[dict] = []
        params: dict = {
            "limit": 100,
            "created[gte]": since_unix,
            "created[lte]": until_unix,
        }
        while True:
            data = http_mod.get_json(
                "https://api.stripe.com/v1/charges",
                headers={"Authorization": f"Bearer {self._env_value()}"},
                params=params,
            )
            batch = data.get("data", [])
            charges.extend(batch)
            if not data.get("has_more") or not batch:
                break
            params["starting_after"] = batch[-1]["id"]
        return [self.normalize(ch) for ch in charges]

    def normalize(self, raw: dict) -> NormalizedTxn:
        # Real Stripe charge shape:
        # { "id": "ch_...", "amount": 2000, "amount_refunded": 0,
        #   "currency": "usd", "created": 1717000000, "description": "...",
        #   "metadata": {"project_id": "..."} }
        gross_cents = raw.get("amount", 0) - raw.get("amount_refunded", 0)
        fee_cents = raw.get("application_fee_amount") or 0
        net_cents = gross_cents - fee_cents
        created_unix = int(raw.get("created", 0))
        occurred = datetime.fromtimestamp(created_unix, tz=timezone.utc).isoformat(timespec="seconds")
        meta = raw.get("metadata") or {}
        return NormalizedTxn(
            external_id=raw["id"],
            project_id=meta.get("project_id", "unassigned"),
            channel_name=meta.get("channel_name", "Stripe import"),
            occurred_at=occurred,
            gross_amount=round(gross_cents / 100.0, 2),
            fee_amount=round(fee_cents / 100.0, 2),
            net_amount=round(net_cents / 100.0, 2),
            currency=raw.get("currency", "usd").upper(),
            kind="recurring" if raw.get("invoice") else "one_time",
            notes=raw.get("description"),
        )


class GumroadConnector(Connector):
    """Gumroad: subscriptions (memberships) and one-time sales."""
    platform_id = "gumroad"
    platform_name = "Gumroad"
    env_var = "AT_GUMROAD_ACCESS_TOKEN"

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        raise NotImplementedError("Gumroad live fetcher not implemented in this loop")

    def normalize(self, raw: dict) -> NormalizedTxn:
        # Gumroad sale shape:
        # { "id": "...", "created_at": "2026-06-15T12:00:00Z", "price": 5000,
        #   "currency": "USD", "email": "buyer@x", "product_name": "...", "recurrence": "monthly" }
        gross_cents = int(raw.get("price", 0))
        # Gumroad fee: 10% flat for most products
        fee_cents = int(gross_cents * 0.10)
        return NormalizedTxn(
            external_id=raw["id"],
            project_id=raw.get("custom_metadata", {}).get("project_id", "unassigned"),
            channel_name=raw.get("product_name", "Gumroad import"),
            occurred_at=raw.get("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            gross_amount=round(gross_cents / 100.0, 2),
            fee_amount=round(fee_cents / 100.0, 2),
            net_amount=round((gross_cents - fee_cents) / 100.0, 2),
            currency=raw.get("currency", "USD"),
            kind="recurring" if raw.get("recurrence") else "one_time",
        )


class BandcampConnector(Connector):
    """Bandcamp: one-time sales + tips."""
    platform_id = "bandcamp"
    platform_name = "Bandcamp"
    env_var = "AT_BANDCAMP_FAN_TOKEN"

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        raise NotImplementedError("Bandcamp live fetcher not implemented in this loop")

    def normalize(self, raw: dict) -> NormalizedTxn:
        # Bandcamp sale shape (sketch — real API differs):
        # { "id": "...", "datetime": "2026-04-20T18:10:00Z",
        #   "amount": "7.00", "currency": "USD", "item_type": "album" }
        return NormalizedTxn(
            external_id=raw["id"],
            project_id=raw.get("project_id", "unassigned"),
            channel_name=raw.get("item_type", "Bandcamp sale"),
            occurred_at=raw["datetime"],
            gross_amount=float(raw.get("amount", 0)),
            fee_amount=round(float(raw.get("amount", 0)) * 0.10, 2),  # ~10% Bandcamp fee
            currency=raw.get("currency", "USD"),
            kind="tip" if raw.get("item_type") == "tip" else "one_time",
        )


class GitHubSponsorsConnector(Connector):
    """GitHub Sponsors: monthly recurring payouts."""
    platform_id = "github_sponsors"
    platform_name = "GitHub Sponsors"
    env_var = "AT_GITHUB_TOKEN"

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        raise NotImplementedError("GitHub Sponsors live fetcher not implemented in this loop")

    def normalize(self, raw: dict) -> NormalizedTxn:
        # GitHub Sponsors webhook payload (sketch):
        # { "id": "evt_...", "created_at": "2026-06-01T00:05:00Z",
        #   "sponsorship": { "tier": {"monthly_price_in_cents": 2500}, "is_one_time_payment": false } }
        cents = int(raw.get("sponsorship", {}).get("tier", {}).get("monthly_price_in_cents", 0))
        is_one_time = raw.get("sponsorship", {}).get("is_one_time_payment", False)
        return NormalizedTxn(
            external_id=raw["id"],
            project_id=raw.get("project_id", "unassigned"),
            channel_name="GitHub Sponsors",
            occurred_at=raw.get("created_at"),
            gross_amount=round(cents / 100.0, 2),
            fee_amount=0.0,  # GitHub covers fees for sponsors
            net_amount=round(cents / 100.0, 2),
            currency="USD",
            kind="one_time" if is_one_time else "recurring",
        )


class EtsyConnector(Connector):
    """Etsy: physical + digital sales."""
    platform_id = "etsy"
    platform_name = "Etsy"
    env_var = "AT_ETSY_API_KEY"

    def _fetch_recent_impl(self, since_iso: str, until_iso: str) -> list[NormalizedTxn]:
        raise NotImplementedError("Etsy live fetcher not implemented in this loop")

    def normalize(self, raw: dict) -> NormalizedTxn:
        return NormalizedTxn(
            external_id=str(raw.get("receipt_id")),
            project_id=raw.get("project_id", "unassigned"),
            channel_name=raw.get("title", "Etsy sale"),
            occurred_at=raw.get("creation_tsz", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            gross_amount=float(raw.get("grandtotal", 0)),
            fee_amount=float(raw.get("total_fee", 0)),
            net_amount=float(raw.get("grandtotal", 0)) - float(raw.get("total_fee", 0)),
            currency=raw.get("currency_code", "USD"),
            kind="one_time",
        )


# ---------- registry ----------

REGISTRY: list[Connector] = [
    StripeConnector(),
    GumroadConnector(),
    BandcampConnector(),
    GitHubSponsorsConnector(),
    EtsyConnector(),
]


def get_connector(platform_id: str) -> Connector:
    conn_obj = next((c for c in REGISTRY if c.platform_id == platform_id), None)
    if not conn_obj:
        raise ValueError(f"unknown platform: {platform_id}")
    return conn_obj


def list_connectors() -> list[dict]:
    """Sprint 9 public API: list connectors + their configured status."""
    out = []
    for c in REGISTRY:
        out.append({
            "name": c.platform_id,
            "platform": c.platform_name,
            "env_var": c.env_var,
            "configured": c.is_configured(),
            "description": f"{c.platform_name} connector (env: {c.env_var or 'none required'})",
        })
    return out


# ---------- import helper (live or mock) ----------

def import_normalized(
    conn: sqlite3.Connection,
    txns: list[NormalizedTxn],
    project_resolver: Optional[dict[str, str]] = None,
    platform_id: str = "other",
) -> tuple[int, int]:
    """Write a list of NormalizedTxn into the local DB.

    Args:
      conn: db connection
      txns: list of NormalizedTxn
      project_resolver: optional {external_project_id: local_project_id} map
                        (for when a connector reports a platform-specific project
                        that we want to remap to a local slug)

    Returns (inserted_count, skipped_count).
    """
    from . import models, repository
    inserted = 0
    skipped = 0
    for nt in txns:
        nt.finalize_net()
        project_id = nt.project_id
        if project_resolver and project_id in project_resolver:
            project_id = project_resolver[project_id]

        # Ensure the project exists; auto-create as 'idea' if unknown.
        if not repository.get_project(conn, project_id):
            repository.create_project(conn, models.Project(
                id=project_id, name=project_id,
                category="other" if "other" in models.VALID_CATEGORIES else "service",
                status="idea",
                notes=f"Auto-created by import at {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            ))

        # Ensure the channel exists
        channels = repository.list_channels(conn, project_id=project_id)
        ch = next((c for c in channels if c.name == nt.channel_name), None)
        if not ch:
            ch_id = repository.create_channel(conn, models.IncomeChannel(
                id=None, project_id=project_id, name=nt.channel_name,
                platform=platform_id if platform_id in models.VALID_PLATFORMS else "other",
                kind=nt.kind,
                currency=nt.currency,
            ))
        else:
            ch_id = ch.id

        tx = models.Transaction(
            id=None, project_id=project_id, channel_id=ch_id,
            occurred_at=nt.occurred_at, gross_amount=nt.gross_amount,
            currency=nt.currency, net_amount=nt.net_amount,
            kind=nt.kind, fee_amount=nt.fee_amount,
            external_id=f"{nt.external_id}",
        )
        result = repository.create_transaction(conn, tx)
        if result == 0:
            skipped += 1
        else:
            inserted += 1
    return (inserted, skipped)


def import_live(
    conn: sqlite3.Connection,
    platform: str,
    since_iso: str,
    until_iso: str,
    project_resolver: Optional[dict[str, str]] = None,
) -> tuple[int, int]:
    """Fetch from a live connector and import into the local DB."""
    connector = get_connector(platform)
    if not connector.is_configured():
        raise ValueError(f"{connector.env_var} not set — add it to .env")
    txns = connector.fetch_recent(since_iso, until_iso)
    return import_normalized(conn, txns, project_resolver, platform_id=connector.platform_id)


def import_mock(conn: sqlite3.Connection, platform: str, count: int = 5) -> tuple[int, int]:
    """Generate `count` synthetic NormalizedTxn from the named connector's normalize() shape.

    Useful for end-to-end testing the import pipeline without hitting any real API.
    """
    conn_obj = next((c for c in REGISTRY if c.platform_id == platform), None)
    if not conn_obj:
        raise ValueError(f"unknown platform: {platform}")
    txns: list[NormalizedTxn] = []
    now = datetime.now(timezone.utc)
    for i in range(count):
        # Synthetic raw shape per platform
        raw = _synthetic_raw(platform, i, now)
        try:
            txns.append(conn_obj.normalize(raw))
        except (KeyError, ValueError, TypeError) as e:
            # Skip malformed samples rather than crash the whole import
            continue
    return import_normalized(conn, txns, platform_id=platform)


def _synthetic_raw(platform: str, idx: int, now: datetime) -> dict:
    """Return a synthetic raw payload that conn.normalize() will accept."""
    if platform == "stripe":
        return {
            "id": f"ch_synth_{idx}_{int(now.timestamp())}",
            "amount": 5000 + idx * 1000,
            "amount_refunded": 0,
            "currency": "usd",
            "created": int(now.timestamp()) - idx * 86400,
            "description": f"Synth Stripe sale #{idx}",
            "metadata": {"project_id": "skull-telegram-gateway", "channel_name": "Gumroad MRR"},
            "invoice": None,
        }
    if platform == "gumroad":
        return {
            "id": f"gr_synth_{idx}_{int(now.timestamp())}",
            "created_at": now.isoformat(timespec="seconds"),
            "price": 2500 + idx * 500,
            "currency": "USD",
            "email": f"buyer{idx}@example.com",
            "product_name": "Synth Product",
            "recurrence": "monthly" if idx % 2 == 0 else None,
        }
    if platform == "bandcamp":
        return {
            "id": f"bc_synth_{idx}_{int(now.timestamp())}",
            "datetime": now.isoformat(timespec="seconds"),
            "amount": "5.00",
            "currency": "USD",
            "item_type": "album" if idx % 2 == 0 else "tip",
        }
    if platform == "github_sponsors":
        return {
            "id": f"gh_synth_{idx}_{int(now.timestamp())}",
            "created_at": now.isoformat(timespec="seconds"),
            "sponsorship": {
                "tier": {"monthly_price_in_cents": 2500},
                "is_one_time_payment": idx == 0,
            },
        }
    if platform == "etsy":
        return {
            "receipt_id": f"etsy_synth_{idx}_{int(now.timestamp())}",
            "creation_tsz": now.isoformat(timespec="seconds"),
            "grandtotal": 30.00 + idx,
            "total_fee": 3.00,
            "currency_code": "USD",
            "title": "Synth Etsy Listing",
        }
    raise ValueError(f"no synthetic raw for platform: {platform}")
