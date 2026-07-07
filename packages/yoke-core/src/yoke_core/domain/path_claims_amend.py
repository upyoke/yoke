"""Amendment surface for path claims.

``widen`` adds coverage, ``narrow`` removes coverage after the
committed-git boundary check, and ``cancel_amendment`` appends an
audit row that reverses a prior amendment without rewriting history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import (
    ClaimNotFound,
    IllegalTransition,
    IncompatibleOverlap,
    InvalidTargetSet,
    PathClaimError,
    get_claim,
)
from yoke_core.domain.path_claims_amend_cancel import (
    AmendmentNotFound,
    cancel_amendment,
)
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckError,
    BoundaryCheckStatus,
    boundary_check_for_paths,
)
from yoke_core.domain.path_claims_boundary_targets import path_strings_for_target_ids
from yoke_core.domain.path_claims_amend_overlap import (
    chosen_serial_upstream,
    classify_widen_overlap,
)


_TERMINAL_STATES = ("released", "cancelled")
_NON_AMENDABLE_STATES = _TERMINAL_STATES
# Amend (widen/narrow) is valid for every non-terminal claim, including
# active claims. Boundary remediation commonly happens after the door
# lock has been acquired; the durable fix is an amendment, a revert, or
# a split, not release/cancel/re-register.


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _executemany(conn: Any, sql: str, rows: Sequence[tuple]) -> None:
    if db_backend.connection_is_postgres(conn):
        with getattr(conn, "_inner", conn).cursor() as cur:
            cur.executemany(sql, rows)
        return
    if hasattr(conn, "executemany"):
        conn.executemany(sql, rows)
        return
    raise AttributeError("connection does not support executemany")


class AmendmentError(PathClaimError):
    """Base class for amendment-surface failures."""


class CannotAmendClaim(AmendmentError):
    """Amendment requested against a claim that is not in an amendable state."""


class NarrowWouldOrphanCommittedWork(AmendmentError):
    """A narrow would drop a path that committed work already touched."""

    def __init__(
        self,
        claim_id: int,
        offending_paths: Sequence[str],
        offending_target_ids: Sequence[int],
    ) -> None:
        self.claim_id = claim_id
        self.offending_paths = list(offending_paths)
        self.offending_target_ids = list(offending_target_ids)
        super().__init__(
            f"narrow rejected for claim {claim_id}: dropping these paths "
            f"would leave committed work outside the claim: "
            f"{', '.join(self.offending_paths)}; widen the keep-list, "
            "revert the out-of-claim change, or split into a separate item"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_amendment(
    conn: Any,
    *,
    claim_id: int,
    kind: str,
    payload: dict,
    reason: str,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_claim_amendments "
        "(claim_id, amended_at, amendment_kind, payload, reason) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id",
        (claim_id, _now(), kind, json.dumps(payload), reason),
    )
    return int(cur.fetchone()[0])


def _validate_amendable(claim: dict) -> None:
    state = str(claim["state"])
    if state in _NON_AMENDABLE_STATES:
        raise CannotAmendClaim(
            f"claim {claim['id']} state={state!r} is not amendable; "
            "release/cancel and re-register if the scope must change"
        )


def _resolved_targets(
    conn: Any, claim_id: int
) -> List[int]:
    p = _p(conn)
    return [
        int(r[0])
        for r in conn.execute(
            "SELECT target_id FROM path_claim_targets "
            f"WHERE claim_id = {p} ORDER BY id",
            (claim_id,),
        )
    ]


def _validate_target_ids(
    conn: Any, target_ids: Iterable[int]
) -> List[int]:
    ids = [int(t) for t in target_ids]
    if not ids:
        raise InvalidTargetSet("amend requires at least one target_id")
    placeholders = ",".join(_p(conn) for _ in ids)
    found = {
        int(r[0])
        for r in conn.execute(
            f"SELECT id FROM path_targets WHERE id IN ({placeholders})",
            tuple(ids),
        )
    }
    missing = [t for t in ids if t not in found]
    if missing:
        raise InvalidTargetSet(
            f"path_targets row(s) {missing!r} do not exist; refresh the registry"
        )
    return ids


def widen(
    conn: Any,
    *,
    claim_id: int,
    add_target_ids: Sequence[int],
    reason: str,
    repo_path: Optional[str] = None,
    worktree_head: Optional[str] = None,
) -> int:
    """Add ``add_target_ids`` to a non-terminal claim's coverage."""
    claim = get_claim(conn, claim_id)
    _validate_amendable(claim)
    add_ids = _validate_target_ids(conn, add_target_ids)
    existing = set(_resolved_targets(conn, claim_id))
    truly_new = [tid for tid in add_ids if tid not in existing]
    if not truly_new:
        amendment_id = _record_amendment(
            conn, claim_id=claim_id, kind="widen",
            payload={
                "added": [], "requested": add_ids,
                "no_op_reason": "all requested targets already declared",
            },
            reason=reason,
        )
        conn.commit()
        return amendment_id
    union = sorted(existing | set(truly_new))
    item_id = claim["item_id"]
    decision = classify_widen_overlap(
        conn, claim_id=claim_id, candidate_target_ids=union,
        integration_target=str(claim["integration_target"]),
        candidate_item_id=int(item_id) if item_id is not None else None,
        current_claim_state=str(claim["state"]),
    )
    if not decision.allowed:
        raise IncompatibleOverlap(
            decision.reason
            or f"widen rejected for claim {claim_id}: overlap is incompatible"
        )
    if repo_path:
        from yoke_core.domain.path_claims_amend_stale_base import (
            check_stale_base_on_new_claim,
        )
        check_stale_base_on_new_claim(
            conn, claim_id=claim_id, new_target_ids=truly_new,
            repo_path=repo_path, worktree_head=worktree_head,
        )
    now = _now()
    p = _p(conn)
    _executemany(
        conn,
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        f"VALUES ({p}, {p}, {p})",
        [(claim_id, tid, now) for tid in truly_new],
    )
    if decision.block_claim:
        chosen = chosen_serial_upstream(decision.upstream_claim_ids)
        conn.execute(
            "UPDATE path_claims SET state = 'blocked', "
            f"blocked_reason = {p} WHERE id = {p}",
            (f"serial-via-dependency on path_claims.id={chosen}", claim_id),
        )
    payload: dict = {"added": truly_new}
    if decision.upstream_claim_ids:
        payload["serial_upstream_claim_ids"] = decision.upstream_claim_ids
    if decision.overlapping_claim_ids:
        payload["overlapping_claim_ids"] = decision.overlapping_claim_ids
    amendment_id = _record_amendment(
        conn, claim_id=claim_id, kind="widen",
        payload=payload, reason=reason,
    )
    conn.commit()
    return amendment_id


def narrow(
    conn: Any,
    *,
    claim_id: int,
    drop_target_ids: Sequence[int],
    reason: str,
    repo_path: str,
    worktree_head: Optional[str] = None,
) -> int:
    """Remove ``drop_target_ids`` from a non-terminal claim's coverage."""
    claim = get_claim(conn, claim_id)
    _validate_amendable(claim)
    drop_ids = _validate_target_ids(conn, drop_target_ids)
    existing = _resolved_targets(conn, claim_id)
    keep_ids = [tid for tid in existing if tid not in set(drop_ids)]
    if not keep_ids:
        raise InvalidTargetSet(
            "narrow rejected: at least one target must remain — "
            "release or cancel the claim instead"
        )
    project_id = _project_for_claim(conn, claim)
    if not project_id:
        raise CannotAmendClaim(
            f"claim {claim_id} has no item project — cannot run boundary check"
        )
    candidate_paths = path_strings_for_target_ids(conn, keep_ids)
    try:
        result = boundary_check_for_paths(
            conn,
            project_id=project_id,
            candidate_paths=candidate_paths,
            integration_target=str(claim["integration_target"]),
            repo_path=repo_path,
            worktree_head=worktree_head,
        )
    except BoundaryCheckError as exc:
        raise CannotAmendClaim(
            f"narrow boundary check failed for claim {claim_id}: {exc}"
        ) from exc
    if result.uncommitted_paths:
        raise CannotAmendClaim(
            f"narrow rejected for claim {claim_id}: resolve staged, "
            "unstaged, or untracked worktree changes before amending: "
            f"{', '.join(result.uncommitted_paths)}"
        )
    if result.status is BoundaryCheckStatus.CONFLICT:
        raise NarrowWouldOrphanCommittedWork(
            claim_id=claim_id,
            offending_paths=result.undeclared_paths,
            offending_target_ids=result.undeclared_target_ids,
        )
    p = _p(conn)
    placeholders = ",".join(p for _ in drop_ids)
    conn.execute(
        f"DELETE FROM path_claim_targets "
        f"WHERE claim_id = {p} AND target_id IN ({placeholders})",
        (claim_id, *drop_ids),
    )
    amendment_id = _record_amendment(
        conn,
        claim_id=claim_id,
        kind="narrow",
        payload={"removed": drop_ids},
        reason=reason,
    )
    from yoke_core.domain.path_targets_materialization import (
        abandon_planned_targets_without_open_claim,
    )
    abandon_planned_targets_without_open_claim(
        conn, target_ids=drop_ids, reason=reason,
    )
    conn.commit()
    return amendment_id


def _project_for_claim(
    conn: Any, claim: dict
) -> Optional[int]:
    item_id = claim.get("item_id")
    if item_id is None:
        return None
    p = _p(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    project_id = row[0] if not hasattr(row, "keys") else row["project_id"]
    return int(project_id) if project_id else None


__all__ = ["AmendmentError", "AmendmentNotFound", "CannotAmendClaim",
           "ClaimNotFound", "IllegalTransition", "IncompatibleOverlap",
           "InvalidTargetSet", "NarrowWouldOrphanCommittedWork",
           "cancel_amendment", "narrow", "widen"]
