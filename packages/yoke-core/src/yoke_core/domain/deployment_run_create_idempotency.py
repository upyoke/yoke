"""Caller-keyed replay for deployment-run creation.

A create command can yield, or lose its response, after the control plane has
already committed the run. Repeating it blind mints a second run of the same
candidate. The caller therefore names each intended run with an idempotency
key, stored on the run it created together with the canonical request. A
repeat with the same key and the same request returns the original run; the
same key with a materially different request refuses by name. Flow plus commit
is deliberately not an identity: an operator may create another run of the
same candidate on purpose, and does so with a new key.

The key lives on the ``deployment_runs`` row itself, written in the creation
transaction that already holds the table lock, so the check and the insert are
one atomic step under concurrent retries. A partial unique index backs that
serialization at the storage layer.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

KEY_COLUMN = "create_idempotency_key"
REQUEST_COLUMN = "create_request"
KEY_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_deployment_runs_create_idempotency "
    f"ON deployment_runs(project_id, {KEY_COLUMN}) "
    f"WHERE {KEY_COLUMN} IS NOT NULL"
)
MAX_KEY_LENGTH = 200
#: The request fields whose values make two creates the same intended run.
REQUEST_FIELDS = (
    "project",
    "flow",
    "environment",
    "release_lineage",
    "retry_of",
    "artifact_identity",
    "created_by",
)


class IdempotencyKeyConflict(ValueError):
    """The key already names a run created from a different request."""

    code = "idempotency_key_conflict"

    def __init__(self, key: str, run_id: str, differing: list[str]) -> None:
        self.run_id = run_id
        super().__init__(
            f"idempotency key {key!r} already created {run_id} from a "
            f"different request (differs in: {', '.join(differing)}). A repeat "
            "must resend the identical request to get that run back; a new, "
            "intentional deployment needs a new --idempotency-key."
        )


def validate_key(value: Any) -> Optional[str]:
    """Return an error message for an unusable key, or None."""
    if not isinstance(value, str) or not value.strip():
        return "idempotency_key must be a non-empty string"
    if len(value.strip()) > MAX_KEY_LENGTH:
        return f"idempotency_key must be at most {MAX_KEY_LENGTH} characters"
    return None


def canonical_request(fields: Mapping[str, Optional[str]]) -> str:
    """Serialize the identity-bearing request fields deterministically."""
    normalized = {
        name: ((fields.get(name) or "").strip() or None) for name in REQUEST_FIELDS
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def existing_run(conn: Any, project_id: int, key: str, request: str) -> Optional[str]:
    """Return the run this key already created for this request.

    Raises :class:`IdempotencyKeyConflict` when the key already names a run
    created from a different request.
    """
    row = conn.execute(
        f"SELECT id, {REQUEST_COLUMN} FROM deployment_runs "
        f"WHERE project_id = %s AND {KEY_COLUMN} = %s",
        (project_id, key),
    ).fetchone()
    if row is None:
        return None
    run_id, stored = str(row[0]), row[1]
    if stored == request:
        return run_id
    before = json.loads(stored) if stored else {}
    after = json.loads(request)
    differing = sorted(
        name for name in REQUEST_FIELDS if before.get(name) != after.get(name)
    )
    raise IdempotencyKeyConflict(key, run_id, differing or ["request"])


def replay_run(project: str, key: str, request: str) -> Optional[str]:
    """Read-only replay lookup made before any create-time gate runs.

    A replay returns a run that already exists, so it needs neither the deploy
    lock nor the candidate checks a fresh create does; a caller whose original
    invocation already released its lock still gets its run back.
    """
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project_id

    conn = connect(None)
    try:
        return existing_run(conn, resolve_project_id(conn, project), key, request)
    finally:
        conn.close()


__all__ = [
    "IdempotencyKeyConflict",
    "KEY_COLUMN",
    "KEY_INDEX_SQL",
    "MAX_KEY_LENGTH",
    "REQUEST_COLUMN",
    "canonical_request",
    "existing_run",
    "replay_run",
    "validate_key",
]
