"""Retired CLI commands for legacy SQLite-file migration audit inspection."""

from __future__ import annotations

import sys
from typing import List, Optional

RETIRED_SQLITE_CLI_MESSAGE = (
    "Legacy SQLite-file migration harness CLI commands are retired. "
    "Yoke authority is Postgres-native; use the migration_apply Postgres "
    "rollback/audit flow or db_router-backed inspection surfaces instead."
)


def _fail_retired_sqlite_cli() -> None:
    print(RETIRED_SQLITE_CLI_MESSAGE, file=sys.stderr)
    raise SystemExit(1)


def cmd_audit_list(db_path: str) -> None:
    """Fail closed: path-based SQLite audit inspection is retired."""
    _fail_retired_sqlite_cli()


def cmd_verify(db_path: str) -> None:
    """Fail closed: path-based SQLite authority verification is retired."""
    _fail_retired_sqlite_cli()


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if len(args) < 2:
        print(
            "Usage: python3 -m yoke_core.domain.migration_harness <cmd> <db-path>\n"
            "Commands: verify, audit-list (retired; fail closed)",
            file=sys.stderr,
        )
        sys.exit(2)

    cmd, db_path = args[0], args[1]

    if cmd == "verify":
        cmd_verify(db_path)
    elif cmd == "audit-list":
        cmd_audit_list(db_path)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
