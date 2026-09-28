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

Those columns are additive, so they arrive when the serving build's boot
converge runs. A self-deploy creates the production run from a driver already
at the new release against a database still serving the old one — the release
that converges the columns is the run being created. Until then the key cannot
be stored, and creation matches by request instead: under the same table lock,
a never-started run with the identical stored request is the one a repeat
returns. The receipt names that basis so a caller never mistakes it for a
recorded key.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from yoke_contracts.deployment_itemless_teaching import (
    BASIS_RECORDED_KEY,
    BASIS_UNCONVERGED_REQUEST_MATCH,
)
from yoke_core.domain.schema_common import _column_exists

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


class UnconvergedReplayAmbiguous(ValueError):
    """More than one never-started run matches an unconverged keyed request."""

    code = "idempotency_replay_ambiguous"

    def __init__(self, key: str, run_ids: list[str]) -> None:
        self.run_ids = run_ids
        super().__init__(
            f"idempotency key {key!r} cannot be stored because "
            "deployment_runs has not converged its create_idempotency_key "
            "column, and the request matches more than one run that has not "
            f"started ({', '.join(run_ids)}), so a repeat cannot tell which one "
            "it created. Drive the one you mean with `yoke watch deploy -- "
            "RUN-ID` and close the others with `yoke deployment-runs "
            "terminalize RUN-ID --disposition cancelled --reason "
            "duplicate-create`."
        )


def key_columns_converged(conn: Any) -> bool:
    """Whether this database can store a create key with its request."""
    return _column_exists(conn, "deployment_runs", KEY_COLUMN) and _column_exists(
        conn, "deployment_runs", REQUEST_COLUMN
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


def unconverged_match(
    conn: Any,
    key: str,
    *,
    project_id: int,
    flow: str,
    target_environment_id: Optional[int],
    release_lineage: Optional[str],
    artifact_identity: Optional[str],
    created_by: str,
) -> Optional[str]:
    """Return the never-started run this request already created, pre-converge.

    Matches the stored, resolved request on a run still ``created``: a repeat
    of a create that lost its response is exactly that run. Once a run starts,
    a new create of the same candidate is a new intent. Raises
    :class:`UnconvergedReplayAmbiguous` when several such runs match.
    """
    clauses = [
        "project_id = %s",
        "flow = %s",
        "status = 'created'",
        "created_by = %s",
        "target_environment_id IS NOT DISTINCT FROM %s",
        "release_lineage IS NOT DISTINCT FROM %s",
    ]
    params: list[Any] = [
        project_id,
        flow,
        created_by,
        target_environment_id or None,
        release_lineage or None,
    ]
    if _column_exists(conn, "deployment_runs", "artifact_identity"):
        clauses.append("artifact_identity IS NOT DISTINCT FROM %s")
        params.append(artifact_identity or None)
    rows = conn.execute(
        f"SELECT id FROM deployment_runs WHERE {' AND '.join(clauses)} "
        "ORDER BY id",
        tuple(params),
    ).fetchall()
    run_ids = [str(row[0]) for row in rows]
    if len(run_ids) > 1:
        raise UnconvergedReplayAmbiguous(key, run_ids)
    return run_ids[0] if run_ids else None


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
        # Unconverged, the key is not stored; the locked create matches by
        # request instead, so this early lookup has nothing to find.
        if not key_columns_converged(conn):
            return None
        return existing_run(conn, resolve_project_id(conn, project), key, request)
    finally:
        conn.close()


__all__ = [
    "BASIS_RECORDED_KEY",
    "BASIS_UNCONVERGED_REQUEST_MATCH",
    "IdempotencyKeyConflict",
    "KEY_COLUMN",
    "KEY_INDEX_SQL",
    "MAX_KEY_LENGTH",
    "REQUEST_COLUMN",
    "canonical_request",
    "existing_run",
    "UnconvergedReplayAmbiguous",
    "key_columns_converged",
    "replay_run",
    "unconverged_match",
    "validate_key",
]
