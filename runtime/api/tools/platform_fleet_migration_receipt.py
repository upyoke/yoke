"""Read fleet tenant-migration receipts from the Platform control-plane DB.

The fleet migration workflow validates the migration command's stdout as a
JSON receipt and discards its temp file. When that validation rejects the
output the workflow fails without ever surfacing the run id, even though the
run itself is recorded durably in the Platform database
(``tenant_migration_runs`` / ``tenant_migration_targets``).

This reader resolves the selected Postgres authority, re-points it at the
Platform control-plane database on the same cluster, and prints run and
per-target state. Those tables record names, hashes, counts, states, and
backup paths — never a DSN or password — so the receipt is safe to print.

Usage::

    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.platform_fleet_migration_receipt
    YOKE_ENV=prod-db-admin python3 -m runtime.api.tools.platform_fleet_migration_receipt <run-id>
"""

from __future__ import annotations

import sys
from typing import Any, Optional, Sequence

import psycopg

from yoke_core.domain import db_backend


PLATFORM_DB = "yoke_platform"
RUNS_TABLE = "tenant_migration_runs"
TARGETS_TABLE = "tenant_migration_targets"


def _platform_dsn() -> str:
    """Return the selected authority DSN re-pointed at the Platform DB."""
    with psycopg.connect(db_backend.resolve_pg_dsn()) as conn:
        info = conn.info
        host, port, user, password = info.host, info.port, info.user, info.password
    parts = [f"host={host}", f"port={port}", f"user={user}", f"dbname={PLATFORM_DB}"]
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


def _dump(cur: Any, label: str) -> list[tuple]:
    rows = cur.fetchall()
    cols = [d.name for d in (cur.description or [])]
    print(f"--- {label} ---")
    if not rows:
        print("(none)")
        return []
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    return rows


def _run_key(cur: Any, rows: Sequence[tuple]) -> Optional[int]:
    cols = [d.name for d in (cur.description or [])]
    for candidate in ("run_id", "id"):
        if candidate in cols:
            return cols.index(candidate)
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    wanted = args[0] if args else None

    with psycopg.connect(_platform_dsn()) as conn:
        with conn.cursor() as cur:
            if wanted:
                # Accept a full run id or the short prefix that names a
                # preserved validation database (yoke_validation_<prefix>_<n>).
                cur.execute(
                    f"SELECT id, module_names, status, failure_reason, "
                    f"rehearsed_at, completed_at, created_at "
                    f"FROM {RUNS_TABLE} WHERE left(id, %s) = %s "
                    f"ORDER BY created_at DESC",
                    (len(wanted), wanted),
                )
            else:
                # manifest_text is a whole embedded manifest; omit it so the
                # receipt stays readable.
                cur.execute(
                    f"SELECT id, module_names, status, failure_reason, "
                    f"coverage, rehearsed_at, completed_at, created_at "
                    f"FROM {RUNS_TABLE} ORDER BY created_at DESC LIMIT 6"
                )
            runs = _dump(cur, "runs")
            key_idx = _run_key(cur, runs)

            for row in runs:
                if key_idx is None:
                    break
                key = row[key_idx]
                cur.execute(
                    f"SELECT * FROM {TARGETS_TABLE} WHERE run_id::text = %s "
                    f"ORDER BY 1",
                    (str(key),),
                )
                _dump(cur, f"targets for run {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
