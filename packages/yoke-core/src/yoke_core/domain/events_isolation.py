"""Event write-isolation gate for the Yoke event platform.

This module owns the contamination guard that the structured-logging-isolation
contract requires.  It is the single source of truth for:

- Deciding whether a particular emission must be refused based on the
  configured isolation/capture env vars, explicit test DB authority, and the
  caller's escape-hatch signals (explicit connection, ``synthetic_smoke``
  lineage flag, or capture sink configured).

The gate is the write-time defense against live-ledger contamination.
``yoke_core.domain.events`` re-exports the public symbols so external
callers continue to import from ``yoke_core.domain.events``.

Design contract:
- ``isolation_gate_blocks`` is a pure function — it reads only the env vars
  named below and the parameters passed in.  It never opens a DB or writes.
- Postgres test authority is identified by the configured DSN target database
  carrying the shared ``yoke_test_`` prefix.  The gate never infers control
  plane authority from legacy file path identity.
- The capture-without-sink case (``YOKE_EVENTS_CAPTURE=1`` without
  ``YOKE_EVENTS_FILE``) is a declared capture intent with no sink
  configured, and is always treated as a refusal regardless of isolation
  mode so that capture-mode callers cannot silently leak into the live DB when
  their file configuration is missing.
"""

from __future__ import annotations

import os
from typing import Optional


def _resolve_db_path() -> Optional[str]:
    """Resolve the legacy file DB path via :func:`db_helpers.resolve_db_path`.

    Post-filters to require an existing file so this writer never mints a
    fresh SQLite file from a silently-wrong env var or stray fallback.
    """
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        candidate = resolve_db_path()
    except (FileNotFoundError, ImportError, RuntimeError):
        return None
    return candidate if os.path.isfile(candidate) else None


# ---------------------------------------------------------------------------
# Event-ledger write isolation
# ---------------------------------------------------------------------------
#
# The isolation gate is the write-time contract for synthetic telemetry:
# when ``YOKE_EVENTS_ISOLATION=1`` is set, event emission must NOT fall
# through to the live ledger unless the caller has explicitly opted in
# via one of these escape hatches:
#
#   1. Postgres authority targets a ``yoke_test_`` database.
#   2. ``YOKE_EVENTS_CAPTURE=1`` + ``YOKE_EVENTS_FILE`` (capture sink).
#   3. ``anomaly_flags`` contains the token ``synthetic_smoke`` — the stable
#      machine-readable lineage marker for intentional smoke rows that a
#      future cleanup pass must preserve.
#
# When isolation is active and none of the escape hatches apply, the gate
# refuses emission silently (logs at DEBUG).  This replaces the old
# query-time defense-in-depth filter as the primary contamination guard.
#
# The capture-without-sink test suite additionally asserts this case:
# ``YOKE_EVENTS_CAPTURE=1`` without ``YOKE_EVENTS_FILE`` is a declared
# capture intent with no sink configured, and is always treated as a refusal
# regardless of isolation mode so that capture-mode callers cannot silently
# leak into the live DB when their file configuration is missing.

SYNTHETIC_SMOKE_FLAG = "synthetic_smoke"


def _anomaly_flags_contain(flags: Optional[str], token: str) -> bool:
    if not flags:
        return False
    return token in {part.strip() for part in flags.split(",") if part.strip()}


def _postgres_dbname_from_dsn(dsn: str) -> Optional[str]:
    """Extract the target database from a libpq DSN without opening a socket."""
    try:
        from psycopg.conninfo import conninfo_to_dict

        value = conninfo_to_dict(dsn).get("dbname")
    except Exception:
        value = None
        for part in dsn.split():
            if part.startswith("dbname="):
                value = part.split("=", 1)[1].strip("'\"")
    return str(value) if value else None


def _postgres_authority_is_test() -> bool:
    """Return True when the active Postgres authority is a Yoke test DB."""
    try:
        from yoke_core.domain import db_backend

        dbname = _postgres_dbname_from_dsn(db_backend.resolve_pg_dsn())
    except (ImportError, RuntimeError, ValueError):
        return False
    return bool(dbname and dbname.startswith(db_backend.POSTGRES_TEST_DB_PREFIX))


def _explicit_file_test_db_is_configured(db_path: Optional[str]) -> bool:
    """Explicit file path tokens are never active authority under Postgres."""
    return False


def isolation_gate_blocks(
    *,
    db_path: Optional[str],
    anomaly_flags: Optional[str],
    has_explicit_conn: bool,
) -> bool:
    """Return True when this emission must be refused for contamination safety.

    Parameters match what the emitter already has in scope:
    - ``db_path``: the already-resolved legacy file DB path (or ``None``).
    - ``anomaly_flags``: the envelope anomaly_flags string, used to detect
      intentional ``synthetic_smoke`` tagging.
    - ``has_explicit_conn``: True when the caller passed an explicit
      connection (test-owned lifecycle) — always honored.

    The two env-var contracts:
    - ``YOKE_EVENTS_CAPTURE=1`` without ``YOKE_EVENTS_FILE`` is a
      declared capture intent with no sink — refuse unconditionally so no
      live-ledger fallthrough can silently occur.
    - ``YOKE_EVENTS_ISOLATION=1`` is the write-time test contract — refuse
      live-ledger writes unless one of the escape hatches applies.
    """
    capture_mode = os.environ.get("YOKE_EVENTS_CAPTURE") == "1"
    capture_file = os.environ.get("YOKE_EVENTS_FILE")

    # Capture-intent-without-sink: unconditional refusal.
    if capture_mode and not capture_file:
        return True

    isolation = os.environ.get("YOKE_EVENTS_ISOLATION") == "1"
    if not isolation:
        return False

    # Explicit test-owned connection is an escape hatch — the caller manages
    # lifecycle, so we never refuse.
    if has_explicit_conn:
        return False

    # Intentional smoke row with lineage marker is an escape hatch.
    if _anomaly_flags_contain(anomaly_flags, SYNTHETIC_SMOKE_FLAG):
        return False

    # Capture sink configured is an escape hatch — file path takes over.
    if capture_mode and capture_file:
        return False

    # Test DB authority is an escape hatch. On Postgres this is the configured
    # DSN's ``yoke_test_`` database; legacy file-backed tests must set
    # YOKE_DB explicitly to the path token they pass through the gate.
    if _postgres_authority_is_test() or _explicit_file_test_db_is_configured(db_path):
        return False

    # No escape hatch applies: the write would target the live ledger.
    return True
