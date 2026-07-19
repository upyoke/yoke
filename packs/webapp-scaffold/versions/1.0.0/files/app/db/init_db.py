#!/usr/bin/env python3
"""Initialize the {{project_display_name}} SQLite database from schema.sql.

Usage:
    python3 db/init_db.py [--db-path PATH]

Creates the database at the path specified by --db-path or APP_DB_PATH env.
Safe to re-run: uses CREATE TABLE IF NOT EXISTS.
"""

import argparse
import os
import sys

# Add app root to path so utils can be imported
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from utils.db import get_connection, get_db_path  # noqa: E402


def init_db(db_path=None):
    path = db_path or get_db_path()

    # Ensure data directory exists
    data_dir = os.path.dirname(path)
    os.makedirs(data_dir, exist_ok=True)

    # Read schema
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()

    # Execute schema
    conn = get_connection(db_path=path)
    try:
        conn.executescript(schema_sql)
        conn.close()
    except Exception:
        conn.close()
        raise

    # Verify tables
    conn = get_connection(db_path=path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()

    expected = sorted(["orgs", "org_members", "sessions", "users"])
    actual = sorted([t for t in tables if t != "sqlite_sequence"])

    if actual != expected:
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        msg = f"Table mismatch. Missing: {missing or 'none'}. Extra: {extra or 'none'}."
        print(f'{{"status": "error", "error": "{msg}"}}')
        sys.exit(1)

    print(f'{{"status": "ok", "data": {{"db_path": "{path}", "tables": {len(actual)}}}}}')


def main():
    parser = argparse.ArgumentParser(description="Initialize {{project_display_name}} database")
    parser.add_argument("--db-path", help="Path to SQLite database file")
    args = parser.parse_args()
    init_db(db_path=args.db_path)


if __name__ == "__main__":
    main()
