-- {{project_display_name}} — Database Schema
-- All timestamps are UTC. SQLite datetime('now') returns UTC.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Organizations
CREATE TABLE IF NOT EXISTS orgs (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    created_at  DATETIME DEFAULT (datetime('now'))
);

-- Users
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    name            TEXT,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK (role IN ('superadmin', 'admin', 'member', 'viewer')),
    api_key         TEXT UNIQUE,
    created_at      DATETIME DEFAULT (datetime('now'))
);

-- Org membership (many-to-many)
CREATE TABLE IF NOT EXISTS org_members (
    org_id      INTEGER NOT NULL REFERENCES orgs(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    role        TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at  DATETIME DEFAULT (datetime('now')),
    PRIMARY KEY (org_id, user_id)
);

-- Auth sessions
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME DEFAULT (datetime('now'))
);
