"""Establish the idempotent application schema owned by schema.sql."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema.sql"
EXPECTED_TABLES = frozenset({"orgs", "org_members", "sessions", "users"})


def _schema_statements():
    pending = ""
    for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        pending += line
        if not sqlite3.complete_statement(pending):
            continue
        statement, pending = pending.strip(), ""
        if statement and not statement.upper().startswith("PRAGMA"):
            yield statement
    if pending.strip():
        raise RuntimeError(f"Incomplete SQL statement in {SCHEMA_PATH}")


def apply(conn) -> None:
    for statement in _schema_statements():
        conn.execute(statement)


def invariants(conn) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {str(row[0]) for row in rows}
    missing = sorted(EXPECTED_TABLES - present)
    if missing:
        raise AssertionError("initial application schema missing: " + ", ".join(missing))
