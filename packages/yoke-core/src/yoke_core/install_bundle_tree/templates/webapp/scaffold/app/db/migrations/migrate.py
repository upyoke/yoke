#!/usr/bin/env python3
"""{{project_display_name}} Python migration runner.

Usage:
    python3 db/migrations/migrate.py [--db-path PATH]

Migration files live next to this runner as ``NNN_name.py`` modules. Each
module must expose ``apply(conn)`` and may expose ``invariants(conn)``.
The numeric prefix is recorded in ``schema_version`` after a successful
apply, so re-running the command applies only pending modules.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

APP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_DIR))

from utils.db import get_connection


MIGRATIONS_DIR = Path(__file__).resolve().parent
MIGRATION_RE = re.compile(r"^(\d+)_[a-zA-Z0-9_]+\.py$")


def get_current_version(conn):
    """Return current schema version, or 0 before any module has run."""
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except Exception:
        return 0


def ensure_schema_version(conn):
    """Create the migration version table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  DATETIME DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def find_pending_migrations(current_version):
    """Find Python migration modules with a version above current_version."""
    pending = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name in {"__init__.py", "migrate.py"}:
            continue
        match = MIGRATION_RE.match(path.name)
        if not match:
            continue
        version = int(match.group(1))
        if version > current_version:
            pending.append((version, path.stem, path))
    return sorted(pending, key=lambda item: (item[0], item[1]))


def load_migration_module(identifier: str, path: Path) -> ModuleType:
    """Load a migration module from a file path."""
    spec = importlib.util.spec_from_file_location(
        f"_{{project_slug}}_migration_{identifier}", path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load migration module {identifier} at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "apply", None)):
        raise RuntimeError(f"Migration {identifier} must define apply(conn)")
    return module


def apply_migration(conn, version: int, identifier: str, path: Path):
    """Apply one Python migration module inside a transaction."""
    module = load_migration_module(identifier, path)
    try:
        conn.execute("BEGIN")
        module.apply(conn)
        invariants = getattr(module, "invariants", None)
        if callable(invariants):
            invariants(conn)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (version,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def migrate(db_path=None):
    """Run pending Python migration modules. Returns a result dict."""
    conn = get_connection(db_path=db_path)
    try:
        ensure_schema_version(conn)
        current = get_current_version(conn)
        pending = find_pending_migrations(current)

        if not pending:
            return {
                "status": "ok",
                "data": {
                    "current_version": current,
                    "applied": 0,
                    "message": "Already up to date",
                },
            }

        applied = []
        for version, identifier, path in pending:
            apply_migration(conn, version, identifier, path)
            applied.append({"version": version, "module": identifier})

        return {
            "status": "ok",
            "data": {
                "previous_version": current,
                "current_version": get_current_version(conn),
                "applied": len(applied),
                "migrations": applied,
            },
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Run {{project_display_name}} database migrations",
    )
    parser.add_argument("--db-path", help="Path to SQLite database file")
    args = parser.parse_args()

    result = migrate(db_path=args.db_path)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
