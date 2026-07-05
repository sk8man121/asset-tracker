# Asset Tracker — Data Model

**Goal:** A single source of truth for every personal side project, software asset, musical/creative venture, and the income each generates.

## Core Entities

### 1. `projects`
A discrete venture. Each project has:

| Field             | Type     | Required | Notes                                                                  |
|-------------------|----------|----------|------------------------------------------------------------------------|
| `id`              | TEXT     | yes      | Slug, e.g. `pinball-rebuild`, `skull-telegram-bot`, `book-pmbbss`       |
| `name`            | TEXT     | yes      | Display name                                                           |
| `category`        | TEXT     | yes      | `software`, `music`, `creative`, `content`, `physical`, `service`      |
| `status`          | TEXT     | yes      | `active`, `dormant`, `archived`, `idea`                                |
| `description`     | TEXT     | no       | One-liner                                                              |
| `created_at`      | TEXT     | yes      | ISO 8601 UTC                                                            |
| `started_at`      | TEXT     | no       | When work actually began                                                |
| `tech_stack`      | TEXT     | no       | Comma-separated tags (e.g. `python,fastapi,sqlite`)                     |
| `repo_url`        | TEXT     | no       | Git remote URL                                                         |
| `repo_local_path` | TEXT     | no       | Local checkout path                                                     |
| `time_to_first_income_days` | INTEGER | no | Days from `started_at` to first income tx                       |
| `notes`           | TEXT     | no       | Free-form                                                               |

### 2. `income_channels`
A repeatable income source attached to a project. Recurring or one-time.

| Field        | Type    | Required | Notes                                                  |
|--------------|---------|----------|--------------------------------------------------------|
| `id`         | INTEGER | yes      | Auto-increment PK                                       |
| `project_id` | TEXT    | yes      | FK → `projects.id`                                       |
| `name`       | TEXT    | yes      | e.g. `Gumroad MRR`, `Stripe API tier`, `Bandcamp sales`  |
| `platform`   | TEXT    | yes      | `gumroad`, `stripe`, `bandcamp`, `etsy`, `github_sponsors`, `direct`, `other` |
| `kind`       | TEXT    | yes      | `recurring`, `one_time`, `royalty`, `tip`               |
| `currency`   | TEXT    | yes      | ISO 4217 (`USD`, `EUR`)                                  |
| `fee_pct`    | REAL    | no       | Platform fee (e.g. Gumroad = 10, Stripe = 2.9)          |
| `fee_flat`   | REAL    | no       | Flat fee per transaction (e.g. Stripe $0.30)             |
| `active`     | INTEGER | yes      | 1 = live, 0 = disabled                                  |
| `created_at` | TEXT    | yes      | ISO 8601 UTC                                             |

### 3. `transactions`
Actual money-in events. Single source of truth for revenue.

| Field         | Type    | Required | Notes                                                |
|---------------|---------|----------|------------------------------------------------------|
| `id`          | INTEGER | yes      | Auto-increment PK                                     |
| `project_id`  | TEXT    | yes      | FK → `projects.id`                                     |
| `channel_id`  | INTEGER | yes      | FK → `income_channels.id`                              |
| `occurred_at` | TEXT    | yes      | ISO 8601 UTC                                           |
| `gross_amount` | REAL   | yes      | Pre-fee                                                |
| `currency`    | TEXT    | yes      | ISO 4217                                               |
| `fee_amount`  | REAL    | no       | Defaults to 0; computed if blank using channel rates  |
| `net_amount`  | REAL    | yes      | Computed: gross - fee                                   |
| `kind`        | TEXT    | yes      | `recurring`, `one_time`, `royalty`, `tip`, `refund`    |
| `external_id` | TEXT    | no       | Platform transaction ID (idempotency key)              |
| `notes`       | TEXT    | no       |                                                       |

### 4. `time_logs` (optional)
Time spent on a project — feeds ROI/time-to-income metrics.

| Field         | Type    | Required | Notes                          |
|---------------|---------|----------|--------------------------------|
| `id`          | INTEGER | yes      | Auto-increment PK               |
| `project_id`  | TEXT    | yes      | FK                              |
| `started_at`  | TEXT    | yes      | ISO 8601 UTC                    |
| `ended_at`    | TEXT    | yes      | ISO 8601 UTC                    |
| `minutes`     | INTEGER | yes      | Computed                        |
| `notes`       | TEXT    | no       |                                 |

## Derived Metrics

| Metric                  | Definition                                                           |
|-------------------------|----------------------------------------------------------------------|
| **MRR**                 | Sum of last-30-days recurring tx net, by project / platform / total  |
| **ARR**                 | MRR × 12                                                             |
| **YTD revenue**         | Sum of net_amount for tx in current calendar year                    |
| **Total revenue**       | Sum of all-time net_amount                                            |
| **Project ROI**         | `(net_revenue - 0) / hours_logged`  → revenue per hour                |
| **Time-to-income**      | Days from `projects.started_at` to first non-zero tx                 |
| **Net per platform**    | Group by `transactions.platform` (via channel join), sum net          |
| **Fee burn**            | Sum of (gross - net) over period                                      |

## Storage

- **Engine:** SQLite, single file `data/asset-tracker.db`
- **Backup:** manual via `asset-tracker backup` → snapshot to `data/backups/<timestamp>.db` (keep 7 by default)
- **Export:** JSON dump to `data/export.json` for cross-tool portability
- **Seed:** `seed/seed.json` ships with sample data for sanity tests

## Schema version

`schema_version = 1` — bumped on any non-additive change.

## Out of scope (this loop)

- Multi-currency conversion (everything stored in native currency; summaries include `by_currency` grouping without FX conversion)
- Tax categorization (could be a `tags` column added later)
- Bank reconciliation
- Web UI (TUI only, this loop)
