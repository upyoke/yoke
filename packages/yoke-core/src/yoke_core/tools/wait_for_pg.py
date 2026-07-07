"""Postgres readiness preflight for an externally provided cluster.

Mirrors the local ``pg_testcluster`` readiness gate (``pg_isready`` +
``pg_ctl -w``) for a cluster Yoke does not start itself — the GitHub
Actions ``postgres`` service in CI. ``conftest`` opens an admin connection
to the maintenance database at collection time via
``pg_testdb.setup_ambient_test_db`` with **no retry**; a transient service
hiccup (or the narrow window where ``pg_isready`` reports healthy a beat
before the postmaster accepts ``CREATE DATABASE``) surfaces there as a
cryptic xdist collection crash. Running this preflight first converts that
into a clear, early, retried failure that names the resolved connection
target (password redacted).

Reuses ``db_backend.resolve_pg_dsn`` so the DSN and the maintenance
``dbname=postgres`` target match exactly what the test fixtures' admin
connection uses — no second copy of the DSN-resolution or maintenance-DB
logic.

Usage::

    python3 -m yoke_core.tools.wait_for_pg
    python3 -m yoke_core.tools.wait_for_pg --attempts 60 --delay 1.0
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable, Optional, Sequence

from yoke_core.domain import db_backend

DEFAULT_ATTEMPTS = 30
DEFAULT_DELAY_SECONDS = 1.0
# PostgreSQL's conventional maintenance database — the one always present and
# the target the fixtures' admin connection (CREATE/DROP DATABASE) uses.
MAINTENANCE_DBNAME = "postgres"


def _redact_dsn(dsn: str) -> str:
    """Mask the password value in a libpq key/value DSN for safe logging."""
    return " ".join(
        "password=***" if token.lower().startswith("password=") else token
        for token in dsn.split()
    )


def _probe_once(dsn: str) -> None:
    """Open a maintenance-DB connection and run ``SELECT 1``; raise on failure."""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT 1")


def wait_for_postgres(
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY_SECONDS,
    dsn: Optional[str] = None,
    probe: Callable[[str], None] = _probe_once,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr, flush=True),
) -> bool:
    """Retry-connect to the Postgres maintenance DB until ready or exhausted.

    Returns ``True`` once a probe succeeds, ``False`` after ``attempts``
    consecutive failures. When *dsn* is omitted the target is resolved via
    ``db_backend.resolve_pg_dsn(MAINTENANCE_DBNAME)`` — the same maintenance
    target ``conftest.setup_ambient_test_db``'s admin connection uses.
    """
    target = (
        dsn if dsn is not None else db_backend.resolve_pg_dsn(MAINTENANCE_DBNAME)
    )
    redacted = _redact_dsn(target)
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            probe(target)
        except Exception as exc:  # noqa: BLE001 — readiness retries on ANY connect-class failure
            last_error = exc
            if attempt < attempts:
                sleep(delay)
            continue
        if attempt > 1:
            log(f"wait_for_pg: Postgres ready after {attempt} attempt(s) [{redacted}]")
        return True
    log(
        f"wait_for_pg: Postgres not reachable after {attempts} attempt(s) "
        f"~{delay}s apart at [{redacted}]: {last_error}"
    )
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wait_for_pg",
        description=(
            "Block until the Postgres maintenance database accepts connections. "
            "Preflight gate for the test suite's no-retry admin connection."
        ),
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help=f"Max connection attempts (default {DEFAULT_ATTEMPTS}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds between attempts (default {DEFAULT_DELAY_SECONDS}).",
    )
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    ready = wait_for_postgres(attempts=ns.attempts, delay=ns.delay)
    return 0 if ready else 1


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
