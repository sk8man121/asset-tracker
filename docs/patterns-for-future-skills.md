# Patterns Worth Extracting as Skills

This loop surfaced 4 reusable patterns. Captured here so future skills/ralphs can absorb them.

## 1. SQLite LEFT JOIN cartesian-product trap

**What happened:** `LEFT JOIN time_logs` from `projects` after aggregating `transactions` multiplied minutes by the number of transactions per project. A project with 3 txns reported `300 * 3 = 900 minutes` instead of 300.

**The fix:** Use scalar subqueries instead of cross-joining:

```sql
-- BAD: cartesian product
SELECT p.id, SUM(t.net_amount) AS net, SUM(tl.minutes) AS minutes
FROM projects p
LEFT JOIN transactions t ON t.project_id = p.id AND t.occurred_at >= ? AND t.occurred_at <= ?
LEFT JOIN time_logs tl ON tl.project_id = p.id
GROUP BY p.id

-- GOOD: scalar subqueries
SELECT p.id,
       COALESCE((SELECT SUM(net_amount) FROM transactions t
                 WHERE t.project_id = p.id AND t.occurred_at >= ? AND t.occurred_at <= ?), 0) AS net,
       COALESCE((SELECT SUM(minutes) FROM time_logs tl
                 WHERE tl.project_id = p.id), 0) AS minutes
FROM projects p
```

**Rule:** Any time you `LEFT JOIN` two one-to-many relations to the same parent row, you'll double-count. Use scalar subqueries or pre-aggregated CTEs.

**Caught by:** Sprint 6 audit (10-test suite included `metrics: per-project ROI` which failed on the 3x over-report).

## 2. Backup-dir-from-actual-conn

**What happened:** Code had two paths to resolve "where do backups go":
- `default_db_path()` returns `Path(AT_DB_PATH)` (or default location)
- `conn.execute("PRAGMA database_list").fetchone()["file"]` returns the actual connected file

When user passed a custom `db_path` to `connect()`, these two diverged — backups went to the wrong directory.

**The fix:** Always derive backup destination from the *connection's* actual file, not the *config* default:

```python
def snapshot_to(conn, keep=7):
    src = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    if str(src) == ":memory:" or not src.exists():
        raise ValueError("cannot snapshot in-memory or missing database")
    dest_dir = src.parent / "backups"  # next to the actual file
    ...
```

**Rule:** For any "where do artifacts go" decision, the source of truth is the live conn/handle — not the default-path helper. Otherwise tests and user-overridden paths silently break.

## 3. `NormalizedTxn` connector pattern

**The shape:** When ingesting from multiple external platforms (Stripe, Gumroad, etc.), define a single platform-agnostic intermediate format and a `normalize()` method on each connector:

```python
@dataclass
class NormalizedTxn:
    external_id: str
    project_id: str
    channel_name: str
    occurred_at: str  # ISO 8601
    gross_amount: float
    fee_amount: float = 0.0
    net_amount: Optional[float] = None  # auto-compute if None
    currency: str = "USD"
    kind: str  # recurring / one_time / royalty / tip / refund
    notes: Optional[str] = None

class Connector:
    def normalize(self, raw: dict) -> NormalizedTxn:
        # platform-specific shape → NormalizedTxn
        ...
    def fetch_recent(self, since, until) -> list[NormalizedTxn]:
        # gated behind AT_LIVE_INTEGRATIONS=1
        ...
```

**Why:** Idempotency key (external_id) is the platform's ID, not your local ID. The local `(channel_id, external_id)` UNIQUE constraint then deduplicates cross-platform imports without coupling them to project-specific IDs.

**Pattern applies to:** any multi-source ingestion (CSV import, webhook receivers, RSS feeds, OAuth callbacks).

## 4. Single-session RALPH vs 6h cron cadence

**The decision matrix:**

| Shape | When |
|---|---|
| **Single-session inline** | ~3K LoC, stdlib-only, no external deps, no cross-session state needed |
| **6h cron RALPH** | External API credentials, multi-host coordination, token budget > single session, crash-recovery matters |

**The 6h RALPH is load-bearing for:**
- Credential-dependent loops (live fetch needs secrets that arrive over time)
- Multi-host (scaffold on host A, run on host B)
- Long-running builds where context would otherwise overflow
- Token-budget enforcement (cache_control + watchdog matter when each run is 1.5M+ tokens)

**Single-session is correct for:**
- One-shot CLIs and tools
- Stdlib-only Python with no remote dependencies
- Anything where the agent can hold the full project in working memory

**Rule of thumb:** if the project is `< 5K LoC`, has no external integrations, and finishes in a single context, the inline shape is cheaper and equivalent. Past that, the protocol earns its overhead.
