"""Durable exactly-one-at-a-time intent state for GitHub workflow dispatch.

The GitHub workflow-dispatch endpoint has no idempotency header.  A process can
therefore lose the response after GitHub accepted the POST.  This table records
the scoped logical request and a GitHub-visible correlation token *before* the
POST; a retry recovers the run by that token instead of issuing another POST.
Completed failed runs remain immutable history and advance to a new attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain import json_helper


INTENT_TABLE = "github_workflow_dispatch_intents"
INTENT_TTL_DAYS = 30

GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {INTENT_TABLE} (
  request_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  authorization_scope TEXT NOT NULL,
  payload_checksum TEXT NOT NULL,
  repo TEXT NOT NULL,
  workflow TEXT NOT NULL,
  workflow_ref TEXT NOT NULL,
  inputs TEXT NOT NULL, -- → JSONB on Postgres
  correlation_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'rejected')),
  workflow_run_id TEXT,
  run_url TEXT,
  html_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (request_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_github_workflow_dispatch_intents_created
  ON {INTENT_TABLE}(created_at)
"""


class DispatchIntentStoreError(RuntimeError):
    """Durable dispatch intent state could not be read or updated."""


@dataclass(frozen=True)
class DispatchIntent:
    request_id: str
    attempt: int
    actor_id: str
    authorization_scope: str
    payload_checksum: str
    correlation_id: str
    state: str
    workflow_run_id: str
    run_url: Optional[str]
    html_url: Optional[str]


def _row_to_intent(row: Any) -> DispatchIntent:
    return DispatchIntent(
        request_id=str(row[0]),
        attempt=int(row[1]),
        actor_id=str(row[2]),
        authorization_scope=str(row[3]),
        payload_checksum=str(row[4]),
        correlation_id=str(row[5]),
        state=str(row[6]),
        workflow_run_id=str(row[7] or ""),
        run_url=str(row[8]) if row[8] else None,
        html_url=str(row[9]) if row[9] else None,
    )


def latest_intent(request_id: str) -> Optional[DispatchIntent]:
    """Load the latest immutable attempt for one logical request."""
    from yoke_core.domain import db_helpers

    try:
        with db_helpers.connect() as conn:
            row = conn.execute(
                f"SELECT request_id, attempt, actor_id, authorization_scope, "
                "payload_checksum, correlation_id, state, workflow_run_id, "
                f"run_url, html_url FROM {INTENT_TABLE} "
                "WHERE request_id = %s ORDER BY attempt DESC LIMIT 1",
                (request_id,),
            ).fetchone()
    except Exception as exc:
        raise DispatchIntentStoreError(
            f"could not read workflow dispatch intent: {exc}"
        ) from exc
    return None if row is None else _row_to_intent(row)


def claim_attempt(
    *,
    request_id: str,
    attempt: int,
    actor_id: str,
    authorization_scope: str,
    payload_checksum: str,
    repo: str,
    workflow: str,
    workflow_ref: str,
    inputs: Mapping[str, str],
    correlation_id: str,
) -> bool:
    """Persist a pending attempt; return true only to the POST owner."""
    from yoke_core.domain import db_helpers

    stamp = db_helpers.iso8601_now()
    sql = (
        f"INSERT INTO {INTENT_TABLE} "
        "(request_id, attempt, actor_id, authorization_scope, "
        "payload_checksum, repo, workflow, workflow_ref, inputs, "
        "correlation_id, state, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "'pending', %s, %s) "
        "ON CONFLICT (request_id, attempt) DO NOTHING"
    )
    params = (
        request_id,
        attempt,
        actor_id,
        authorization_scope,
        payload_checksum,
        repo,
        workflow,
        workflow_ref,
        json_helper.dumps_compact(dict(inputs)),
        correlation_id,
        stamp,
        stamp,
    )
    try:
        with db_helpers.connect() as conn:
            claimed = conn.execute(sql, params).rowcount == 1
            conn.commit()
            return claimed
    except Exception as exc:
        raise DispatchIntentStoreError(
            f"could not persist workflow dispatch intent: {exc}"
        ) from exc


def complete_intent(
    intent: DispatchIntent,
    *,
    workflow_run_id: str,
    run_url: Optional[str],
    html_url: Optional[str],
) -> DispatchIntent:
    """Attach GitHub's exact run identity to a pending attempt."""
    from yoke_core.domain import db_helpers

    stamp = db_helpers.iso8601_now()
    try:
        with db_helpers.connect() as conn:
            changed = conn.execute(
                f"UPDATE {INTENT_TABLE} SET state = 'completed', "
                "workflow_run_id = %s, run_url = %s, html_url = %s, "
                "updated_at = %s WHERE request_id = %s AND attempt = %s "
                "AND correlation_id = %s AND state = 'pending'",
                (
                    workflow_run_id,
                    run_url,
                    html_url,
                    stamp,
                    intent.request_id,
                    intent.attempt,
                    intent.correlation_id,
                ),
            ).rowcount
            conn.commit()
    except Exception as exc:
        raise DispatchIntentStoreError(
            f"could not complete workflow dispatch intent: {exc}"
        ) from exc
    if changed != 1:
        current = latest_intent(intent.request_id)
        if (
            current is None
            or current.attempt != intent.attempt
            or current.state != "completed"
            or current.workflow_run_id != workflow_run_id
        ):
            raise DispatchIntentStoreError(
                "workflow dispatch intent changed before completion"
            )
        return current
    return DispatchIntent(
        request_id=intent.request_id,
        attempt=intent.attempt,
        actor_id=intent.actor_id,
        authorization_scope=intent.authorization_scope,
        payload_checksum=intent.payload_checksum,
        correlation_id=intent.correlation_id,
        state="completed",
        workflow_run_id=workflow_run_id,
        run_url=run_url,
        html_url=html_url,
    )


def reject_intent(intent: DispatchIntent) -> None:
    """Mark a server-rejected POST safe for a later fresh attempt."""
    from yoke_core.domain import db_helpers

    try:
        with db_helpers.connect() as conn:
            changed = conn.execute(
                f"UPDATE {INTENT_TABLE} SET state = 'rejected', "
                "updated_at = %s WHERE request_id = %s AND attempt = %s "
                "AND correlation_id = %s AND state = 'pending'",
                (
                    db_helpers.iso8601_now(),
                    intent.request_id,
                    intent.attempt,
                    intent.correlation_id,
                ),
            ).rowcount
            conn.commit()
    except Exception as exc:
        raise DispatchIntentStoreError(
            f"could not reject workflow dispatch intent: {exc}"
        ) from exc
    if changed != 1:
        raise DispatchIntentStoreError(
            "workflow dispatch intent changed before rejection"
        )


def ttl_cutoff_iso(now: Optional[Any] = None) -> str:
    """Return the terminal-intent retention cutoff in UTC."""
    from datetime import datetime, timedelta, timezone

    base = now or datetime.now(timezone.utc)
    return (base - timedelta(days=INTENT_TTL_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def count_expired(conn: Any) -> int:
    """Count terminal attempts past TTL; pending ambiguity is immortal."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, INTENT_TABLE):
        return 0
    row = conn.execute(
        f"SELECT COUNT(*) FROM {INTENT_TABLE} "
        "WHERE state IN ('completed', 'rejected') AND updated_at < %s",
        (ttl_cutoff_iso(),),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def prune_expired(conn: Any) -> int:
    """Delete expired terminal attempts without ever deleting pending rows."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, INTENT_TABLE):
        return 0
    return conn.execute(
        f"DELETE FROM {INTENT_TABLE} "
        "WHERE state IN ('completed', 'rejected') AND updated_at < %s",
        (ttl_cutoff_iso(),),
    ).rowcount


__all__ = [
    "DispatchIntent",
    "DispatchIntentStoreError",
    "GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL",
    "INTENT_TTL_DAYS",
    "INTENT_TABLE",
    "claim_attempt",
    "complete_intent",
    "count_expired",
    "latest_intent",
    "reject_intent",
    "prune_expired",
    "ttl_cutoff_iso",
]
