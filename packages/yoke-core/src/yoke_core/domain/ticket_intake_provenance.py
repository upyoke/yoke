"""Idea-intake provenance signal for public ticket-creation surfaces.

Every backlog ticket enters through ``/yoke idea``. The lower-level
item, body, claim, GitHub, and REST creation primitives are internal
to that workflow — direct real creation outside sanctioned idea intake
is rejected with a recovery hint that names ``/yoke idea``.

Two equivalent sanctioned signals:

- An explicit ``provenance="idea"`` argument threaded through the
  callstack (used by the REST request body and by ``execute_create``
  callers that already have a Python handle).
- The ``YOKE_IDEA_INTAKE`` env var set to a truthy value by the idea
  skill's outer subshell or by Yoke-owned noninteractive filing flows,
  picked up by every adapter that fans out into a subprocess (the CLI
  ``items add`` path, the public backlog registry shape).

Dry-run and test-isolated flows still work without idea provenance
because they never create real backlog rows, increment production
counters, or sync GitHub. Test isolation is detected from the active
Postgres DSN: path-shaped compatibility tokens count as fixtures only
when ``YOKE_PG_DSN`` targets a disposable ``yoke_test_*`` database.

This is an autonomy / teaching boundary, not a credential-security
boundary. It fails closed for production persistent creates when
provenance is missing or unrecognized; the recovery hint points the
caller back at ``/yoke idea``.
"""

from __future__ import annotations

import os
from typing import Optional

from yoke_core.domain import db_backend


IDEA_INTAKE_ENV = "YOKE_IDEA_INTAKE"
IDEA_PROVENANCE_TOKEN = "idea"

BYPASS_MESSAGE = (
    "Ticket creation must enter through `/yoke idea`. Lower-level "
    "item, body, claim, GitHub, and REST creation primitives are "
    "internal to that workflow — do not assemble a ticket yourself. "
    "Recovery: run `/yoke idea \"<title>\"` for new work, or, for "
    "an existing title-only shell, adopt it through the idea workflow "
    "rather than filling it via lower-level APIs."
)


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_idea_intake(provenance: Optional[str] = None) -> bool:
    """Return True when the call carries sanctioned idea provenance."""
    if provenance and provenance.strip().lower() == IDEA_PROVENANCE_TOKEN:
        return True
    env_value = os.environ.get(IDEA_INTAKE_ENV, "")
    return bool(env_value) and _is_truthy(env_value)


def _dsn_dbname(dsn: str) -> Optional[str]:
    found: Optional[str] = None
    for part in dsn.split():
        if part.startswith("dbname="):
            found = part.split("=", 1)[1]
    return found


def _active_dsn_is_test_isolated() -> bool:
    """Return True when the current Postgres target is disposable."""
    dsn = os.environ.get(db_backend.PG_DSN_ENV, "")
    dbname = _dsn_dbname(dsn)
    return bool(
        dbname and dbname.startswith(db_backend.POSTGRES_TEST_DB_PREFIX)
    )


def is_test_isolation(db_path: Optional[str] = None) -> bool:
    """Return True when a path-shaped token is backed by a test DSN.

    The ``execute_create`` path resolves a concrete write-DB path
    early (``yoke_core.domain.backlog_queries._resolve_write_db_path``)
    and passes that path through. Active Postgres authority ignores the path;
    the only safe bypass is a disposable test database selected by
    ``YOKE_PG_DSN``.
    """
    if not db_path:
        return False
    return _active_dsn_is_test_isolated()


def enforce_public_create_allowed(
    *,
    provenance: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Gate public persistent creation surfaces.

    Returns ``None`` when the call is allowed (sanctioned idea intake,
    dry-run preview, or test-isolated DB target). Returns
    :data:`BYPASS_MESSAGE` when the call must be rejected. Callers
    surface the message via their own error envelope shape
    (``{"success": false, "error": ...}`` for the create_op result,
    HTTP 403 JSON for the REST route, non-zero exit for the validator
    CLI).
    """
    if dry_run:
        return None
    if is_idea_intake(provenance):
        return None
    if is_test_isolation(db_path):
        return None
    return BYPASS_MESSAGE


__all__ = [
    "BYPASS_MESSAGE",
    "IDEA_INTAKE_ENV",
    "IDEA_PROVENANCE_TOKEN",
    "is_idea_intake",
    "is_test_isolation",
    "enforce_public_create_allowed",
]
