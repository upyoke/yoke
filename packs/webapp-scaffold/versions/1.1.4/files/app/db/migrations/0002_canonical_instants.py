"""Convert scaffold-owned SQLite instants without rewriting immutable evidence."""

from __future__ import annotations

import re

from utils.timestamps import format_instant, parse_instant

MINIMUM_SERVING_VERSION = "next-release"
TABLE_SQL = {
    "orgs": "CREATE TABLE IF NOT EXISTS orgs (\n    id          INTEGER PRIMARY KEY,\n    name        TEXT NOT NULL UNIQUE,\n    slug        TEXT NOT NULL UNIQUE,\n    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')\n)",
    "users": "CREATE TABLE IF NOT EXISTS users (\n    id              INTEGER PRIMARY KEY,\n    email           TEXT NOT NULL UNIQUE,\n    password_hash   TEXT NOT NULL,\n    name            TEXT,\n    role            TEXT NOT NULL DEFAULT 'member'\n                    CHECK (role IN ('superadmin', 'admin', 'member', 'viewer')),\n    api_key         TEXT UNIQUE,\n    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')\n)",
    "org_members": "CREATE TABLE IF NOT EXISTS org_members (\n    org_id      INTEGER NOT NULL REFERENCES orgs(id),\n    user_id     INTEGER NOT NULL REFERENCES users(id),\n    role        TEXT NOT NULL DEFAULT 'member'\n                CHECK (role IN ('owner', 'admin', 'member', 'viewer')),\n    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z'),\n    PRIMARY KEY (org_id, user_id)\n)",
    "sessions": "CREATE TABLE IF NOT EXISTS sessions (\n    id          TEXT PRIMARY KEY,\n    user_id     INTEGER NOT NULL REFERENCES users(id),\n    expires_at  TEXT NOT NULL,\n    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')\n)",
}
CLOCKS = {
    "orgs": ("created_at",),
    "users": ("created_at",),
    "org_members": ("created_at",),
    "sessions": ("expires_at", "created_at"),
}
LEGACY_UTC = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\Z")


def _normalized(sql):
    for name in TABLE_SQL:
        sql = sql.replace(f'"{name}"', name)
    return " ".join(sql.replace("IF NOT EXISTS ", "").split()).casefold()


def _legacy_sql(sql):
    return sql.replace(
        "TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z')",
        "DATETIME DEFAULT (datetime('now'))",
    ).replace("expires_at  TEXT NOT NULL", "expires_at  DATETIME NOT NULL")


def _clock(value):
    if value is None:
        return None
    # This one-shot migration owns the known prior SQLite/naive UTC producers.
    # Serving callers use only the strict shared qualified-instant parser.
    if isinstance(value, str) and LEGACY_UTC.fullmatch(value):
        value = value.replace(" ", "T") + "Z"
    return format_instant(value)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _preflight(conn):
    tables = {
        name: sql
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"
        )
    }
    for name, expected in TABLE_SQL.items():
        if name not in tables or _normalized(tables[name]) not in {
            _normalized(expected),
            _normalized(_legacy_sql(expected)),
        }:
            raise RuntimeError(
                f"Customized scaffold table {name}; author a project-owned migration"
            )
        extras = conn.execute(
            "SELECT name FROM sqlite_master WHERE tbl_name=? AND type IN ('index', 'trigger') "
            "AND sql IS NOT NULL",
            (name,),
        ).fetchall()
        if extras:
            raise RuntimeError(
                f"Custom dependencies on {name}; author a project-owned migration"
            )
    for name in tables.keys() - TABLE_SQL.keys():
        if any(
            row[2] in TABLE_SQL
            for row in conn.execute(f"PRAGMA foreign_key_list({_quote(name)})")
        ):
            raise RuntimeError(
                f"External foreign key on {name}; author a project-owned migration"
            )
    for name, sql in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='view'"
    ):
        if any(re.search(r"\b" + table + r"\b", sql, re.I) for table in TABLE_SQL):
            raise RuntimeError(
                f"External view {name}; author a project-owned migration"
            )
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError(
            "Existing foreign-key violations refuse the instant conversion"
        )
    prepared = {}
    for name, clocks in CLOCKS.items():
        columns = tuple(row[1] for row in conn.execute(f"PRAGMA table_info({name})"))
        rows = []
        for row in conn.execute(f"SELECT * FROM {name}"):
            values = dict(zip(columns, row))
            for clock in clocks:
                values[clock] = _clock(values[clock])
            if name == "sessions" and values["expires_at"] is None:
                raise RuntimeError("Session expiry cannot be absent")
            rows.append(tuple(values[column] for column in columns))
        prepared[name] = (columns, rows)
    return prepared


def apply(conn):
    # Every value and dependency is validated before the first schema write.
    prepared = _preflight(conn)
    for name, sql in TABLE_SQL.items():
        sql = sql.replace(
            f"CREATE TABLE IF NOT EXISTS {name}", f"CREATE TABLE _instant_{name}"
        )
        for parent in TABLE_SQL:
            sql = sql.replace(f"REFERENCES {parent}(", f"REFERENCES _instant_{parent}(")
        conn.execute(sql)
        columns, rows = prepared[name]
        placeholders = ", ".join("?" for column in columns)
        conn.executemany(f"INSERT INTO _instant_{name} VALUES ({placeholders})", rows)
    for name in reversed(TABLE_SQL):
        conn.execute(f"DROP TABLE {name}")
    for name in TABLE_SQL:
        conn.execute(f"ALTER TABLE _instant_{name} RENAME TO {name}")


def invariants(conn):
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Instant conversion must preserve all foreign keys")
    for name, clocks in CLOCKS.items():
        for clock in clocks:
            info = {row[1]: row for row in conn.execute(f"PRAGMA table_info({name})")}
            if info[clock][2] != "TEXT":
                raise RuntimeError(f"{name}.{clock} must be SQLite TEXT")
            for (value,) in conn.execute(f"SELECT {clock} FROM {name}"):
                if value is not None and format_instant(parse_instant(value)) != value:
                    raise RuntimeError(f"{name}.{clock} must be canonical UTC text")
