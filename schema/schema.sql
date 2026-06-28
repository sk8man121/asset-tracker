-- Asset Tracker — SQLite schema v1
-- 4 tables: projects, income_channels, transactions, time_logs

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS projects (
    id                       TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    category                 TEXT NOT NULL CHECK(category IN ('software','music','creative','content','physical','service')),
    status                   TEXT NOT NULL CHECK(status IN ('active','dormant','archived','idea')),
    description              TEXT,
    created_at               TEXT NOT NULL,
    started_at               TEXT,
    tech_stack               TEXT,
    repo_url                 TEXT,
    repo_local_path          TEXT,
    time_to_first_income_days INTEGER,
    notes                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category);

CREATE TABLE IF NOT EXISTS income_channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    platform    TEXT NOT NULL CHECK(platform IN ('gumroad','stripe','bandcamp','etsy','github_sponsors','direct','other')),
    kind        TEXT NOT NULL CHECK(kind IN ('recurring','one_time','royalty','tip')),
    currency    TEXT NOT NULL DEFAULT 'USD',
    fee_pct     REAL DEFAULT 0,
    fee_flat    REAL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channels_project ON income_channels(project_id);
CREATE INDEX IF NOT EXISTS idx_channels_platform ON income_channels(platform);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    channel_id   INTEGER NOT NULL REFERENCES income_channels(id) ON DELETE CASCADE,
    occurred_at  TEXT NOT NULL,
    gross_amount REAL NOT NULL,
    currency     TEXT NOT NULL,
    fee_amount   REAL DEFAULT 0,
    net_amount   REAL NOT NULL,
    kind         TEXT NOT NULL CHECK(kind IN ('recurring','one_time','royalty','tip','refund')),
    external_id  TEXT,
    notes        TEXT,
    UNIQUE(channel_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_project ON transactions(project_id);
CREATE INDEX IF NOT EXISTS idx_tx_channel ON transactions(channel_id);
CREATE INDEX IF NOT EXISTS idx_tx_occurred ON transactions(occurred_at);
CREATE INDEX IF NOT EXISTS idx_tx_kind ON transactions(kind);

CREATE TABLE IF NOT EXISTS time_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    ended_at    TEXT NOT NULL,
    minutes     INTEGER NOT NULL,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_time_project ON time_logs(project_id);
