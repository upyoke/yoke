"""Path claim lifecycle: register/activate/release/cancel; overlap and exceptions live in sisters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend, workflow_item_binding_lock
from yoke_core.domain.actors import validate_actor_id
from yoke_core.domain.path_claim_owner import (
    derive_owner_from_signals,
    owner_columns_or_null,
)
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)


class PathClaimError(Exception):
    """Base class for path-claim domain failures."""


class InvalidActor(PathClaimError): ...
class InvalidMode(PathClaimError): ...
class InvalidTargetSet(PathClaimError): ...
class IncompatibleOverlap(PathClaimError): ...
class UpstreamNotReleased(PathClaimError): ...
class ClaimNotFound(PathClaimError): ...
class IllegalTransition(PathClaimError): ...
class InvalidWorkflowBinding(PathClaimError): ...


_TERMINAL_STATES = ("released", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _validate_targets(conn: Any, target_ids: Sequence[int]) -> None:
    if not target_ids:
        raise InvalidTargetSet("path-claim register requires at least one target_id")
    placeholders = ",".join(_p(conn) for _ in target_ids)
    found = {
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM path_targets WHERE id IN ({placeholders})",
            tuple(target_ids),
        )
    }
    missing = [t for t in target_ids if int(t) not in found]
    if missing:
        raise InvalidTargetSet(
            f"path_targets row(s) {missing!r} do not exist; refresh the registry"
        )


_CLAIM_COLS = (
    "id, state, mode, owner_kind, owner_item_id, owner_session_id, "
    "owner_work_claim_id, "
    "registered_by_actor_id, registered_by_session_id, integration_target, "
    "base_commit_sha, registered_at, activated_at, released_at, cancelled_at, "
    "release_reason, cancel_reason, blocked_reason, exception_reason"
)


def _fetch_claim(conn: Any, claim_id: int) -> Any:
    row = conn.execute(
        f"SELECT {_CLAIM_COLS} FROM path_claims WHERE id = {_p(conn)}",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise ClaimNotFound(f"path_claims id {claim_id} does not exist")
    return row


def _blocked_upstream_id(row: Any) -> Optional[int]:
    marker = "path_claims.id="
    reason = row["blocked_reason"] or ""
    if marker not in reason:
        return None
    try:
        return int(reason.rsplit(marker, 1)[1].strip())
    except ValueError:
        return None


@workflow_item_binding_lock.rollback_workflow_binding_write_errors
def register(
    conn: Any,
    *,
    actor_id: int,
    integration_target: str,
    target_ids: Sequence[int],
    mode: str = "exclusive",
    session_id: Optional[str] = None,
    item_id: Optional[int] = None,
    upstream_claim_id: Optional[int] = None,
    exception_reason: Optional[str] = None,
    work_claim_id: Optional[int] = None,
    candidate_item_id: Optional[int] = None,
    task_num: Optional[int] = None,
    commit: bool = True,
) -> int:
    """Register a planned path claim; return its row id.

    ``candidate_item_id`` lets overlap classification serialize dependents.
    """
    if mode == "parallel":
        raise InvalidMode("parallel mode is not supported; use exclusive")
    if mode not in ("exclusive", "exception"):
        raise InvalidMode(f"unknown mode {mode!r}; expected 'exclusive' or 'exception'")
    if not validate_actor_id(conn, actor_id):
        raise InvalidActor(f"actor_id {actor_id} does not exist")

    if mode == "exception":
        from yoke_core.domain.path_claims_exception import register_exception

        return register_exception(
            conn,
            actor_id=actor_id,
            integration_target=integration_target,
            target_ids=target_ids,
            exception_reason=exception_reason,
            session_id=session_id,
            item_id=item_id,
            task_num=task_num,
            commit=commit,
        )

    _validate_targets(conn, target_ids)
    workflow_item_binding_lock.lock_optional_item_workflow_binding(conn, item_id)
    from yoke_core.domain.workflow_item_binding_validation import (
        WorkflowItemBindingError,
        validate_item_path_claim_scope,
    )

    try:
        validate_item_path_claim_scope(conn, item_id, task_num=task_num)
    except WorkflowItemBindingError as exc:
        raise InvalidWorkflowBinding(str(exc)) from exc

    effective_candidate_item_id = candidate_item_id or item_id
    classification = classify_overlap(
        conn,
        target_ids=list(target_ids),
        integration_target=integration_target,
        upstream_claim_id=upstream_claim_id,
        candidate_item_id=effective_candidate_item_id,
    )
    if classification is OverlapClassification.INCOMPATIBLE:
        from yoke_core.domain.path_claims_overlap_survey import (
            describe_survey_overlap,
        )

        raise IncompatibleOverlap(
            describe_survey_overlap(
                conn,
                target_ids=list(target_ids),
                integration_target=integration_target,
                candidate_item_id=effective_candidate_item_id,
            )
            or f"path coverage overlaps an active claim on "
            f"{integration_target!r}; declare an upstream dependency or wait"
        )

    is_serial = classification is OverlapClassification.SERIAL_VIA_DEPENDENCY
    initial_state = "blocked" if is_serial else "planned"
    blocked_reason = None
    if is_serial and upstream_claim_id is not None:
        blocked_reason = f"serial-via-dependency on path_claims.id={upstream_claim_id}"
    elif is_serial:
        blocked_reason = "serial-via-dependency"
    oc = owner_columns_or_null(
        derive_owner_from_signals(
            item_id=item_id,
            work_claim_id=work_claim_id,
            session_id=session_id,
        )
    )
    now = _now()
    cur = conn.execute(
        "INSERT INTO path_claims (state, mode, owner_kind, owner_item_id, "
        "owner_session_id, owner_work_claim_id, registered_by_actor_id, "
        "registered_by_session_id, integration_target, registered_at, "
        "blocked_reason) "
        f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, "
        f"{_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, "
        f"{_p(conn)}) RETURNING id",
        (
            initial_state,
            mode,
            oc["owner_kind"],
            oc["owner_item_id"],
            oc["owner_session_id"],
            oc["owner_work_claim_id"],
            actor_id,
            session_id,
            integration_target,
            now,
            blocked_reason,
        ),
    )
    claim_id = int(cur.fetchone()[0])
    for target_id in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)})",
            (claim_id, int(target_id), now),
        )
    if commit:
        conn.commit()
    return claim_id


def activate(
    conn: Any,
    *,
    claim_id: int,
    base_commit_sha: str,
    upstream_claim_id: Optional[int] = None,
) -> None:
    """Acquire the door lock on a planned/blocked claim.

    Idempotent re-activation is a no-op. Same-target overlap is
    re-classified at activate time. ``blocked`` claims require their
    named upstream to be in state ``released``.
    """
    workflow_item_binding_lock.lock_path_claim_workflow_binding(
        conn,
        int(claim_id),
    )
    row = _fetch_claim(conn, claim_id)
    owner_kind = row["owner_kind"]
    owner_item_id = row["owner_item_id"] if owner_kind == "item" else None
    if owner_item_id is not None:
        from yoke_core.domain.workflow_item_binding_validation import (
            WorkflowItemBindingError,
            item_binding_runtime_state,
        )

        try:
            item_binding_runtime_state(conn, int(owner_item_id))
        except WorkflowItemBindingError as exc:
            raise InvalidWorkflowBinding(str(exc)) from exc
    state = row["state"]
    if state == "active":
        return  # idempotent — door lock already held
    if state in _TERMINAL_STATES:
        raise IllegalTransition(
            f"cannot activate claim {claim_id} from terminal state {state!r}"
        )
    if state not in ("planned", "blocked"):
        raise IllegalTransition(f"cannot activate claim {claim_id} from {state!r}")

    targets = [
        int(t[0])
        for t in conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {_p(conn)}",
            (claim_id,),
        )
    ]
    classification = classify_overlap(
        conn,
        target_ids=targets,
        integration_target=row["integration_target"],
        upstream_claim_id=upstream_claim_id,
        exclude_claim_id=claim_id,
        phase="activate",
    )
    if classification is OverlapClassification.INCOMPATIBLE:
        raise IncompatibleOverlap(
            f"claim {claim_id}: another active claim now owns overlapping "
            f"coverage on {row['integration_target']!r}"
        )
    if (
        state == "planned"
        and classification is OverlapClassification.SERIAL_VIA_DEPENDENCY
    ):
        raise UpstreamNotReleased(
            f"claim {claim_id} has an active serial dependency; wait for release"
        )
    if state == "blocked":
        if upstream_claim_id is None:
            raise UpstreamNotReleased(
                f"claim {claim_id} is blocked; pass upstream_claim_id to activate"
            )
        expected_upstream = _blocked_upstream_id(row)
        if (
            expected_upstream is not None
            and int(upstream_claim_id) != expected_upstream
        ):
            raise UpstreamNotReleased(
                f"claim {claim_id} is blocked by upstream claim "
                f"{expected_upstream}, not {upstream_claim_id}"
            )
        upstream_state = conn.execute(
            f"SELECT state FROM path_claims WHERE id = {_p(conn)}",
            (upstream_claim_id,),
        ).fetchone()
        if upstream_state is None or upstream_state[0] != "released":
            raise UpstreamNotReleased(
                f"upstream claim {upstream_claim_id} is not released; "
                f"current state {upstream_state[0] if upstream_state else 'missing'!r}"
            )

    conn.execute(
        f"UPDATE path_claims SET state='active', activated_at={_p(conn)}, "
        f"base_commit_sha={_p(conn)}, blocked_reason=NULL WHERE id = {_p(conn)}",
        (_now(), base_commit_sha, claim_id),
    )
    conn.commit()


def get_claim(conn: Any, claim_id: int) -> dict:
    """Return a claim row as a dict, including its declared target ids."""
    row = _fetch_claim(conn, claim_id)
    targets = [
        int(t[0])
        for t in conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {_p(conn)} "
            "ORDER BY id",
            (claim_id,),
        )
    ]
    out = {k: row[k] for k in _CLAIM_COLS.replace(", ", ",").split(",")}
    out["id"] = int(out["id"])
    if out["registered_by_actor_id"] is not None:
        out["registered_by_actor_id"] = int(out["registered_by_actor_id"])
    out["target_ids"] = targets
    return out


from yoke_core.domain.path_claims_terminal import cancel, release  # noqa: E402


__all__ = [
    "ClaimNotFound", "IllegalTransition", "IncompatibleOverlap", "InvalidActor",
    "InvalidMode", "InvalidTargetSet", "InvalidWorkflowBinding", "PathClaimError",
    "UpstreamNotReleased", "activate", "cancel", "get_claim", "register", "release",
]
