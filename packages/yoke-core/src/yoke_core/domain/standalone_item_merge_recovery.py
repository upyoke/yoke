"""Recover a landed standalone merge whose work claim was reclaimed."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.work_claim_targets import item_id_from_row

_MISSING_CLAIM = "no live work claim on this item"
_HOLDER_FUNCTION = "claims.work.holder_get"
_WORK_CLAIM_LOOKUP: ContextVar[Optional[Mapping[str, Any]]] = ContextVar(
    "standalone_merge_work_claim_lookup",
    default=None,
)


def _relay_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return getattr(error, "message", None) or fallback if error else fallback


def _session_id(explicit: str) -> str:
    return explicit or str(resolve_ambient_session_id() or "")


def _active_connection_name() -> str:
    try:
        from yoke_core.domain import machine_config

        return str(machine_config.active_env() or "unknown")
    except Exception:  # noqa: BLE001 - diagnostics must survive config failure
        return "unknown"


@contextmanager
def bind_work_claim_lookup(
    lookup: Mapping[str, Any],
) -> Iterator[None]:
    """Make one original-connection holder verdict available to the merge."""
    token = _WORK_CLAIM_LOOKUP.set(lookup)
    try:
        yield
    finally:
        _WORK_CLAIM_LOOKUP.reset(token)


def _value(subject: Any, name: str, default: Any = None) -> Any:
    if isinstance(subject, Mapping):
        return subject.get(name, default)
    return getattr(subject, name, default)


def _lookup_failure(connection: str, detail: str) -> str:
    return (
        f"work-claim holder lookup on connection {connection!r} via "
        f"{_HOLDER_FUNCTION} could not be performed: {detail}"
    )


def _claim_error_from_lookup(
    item_id: int,
    session_id: str,
    lookup: Mapping[str, Any],
) -> str:
    connection = str(lookup.get("connection") or "unknown")
    if lookup.get("function_id") != _HOLDER_FUNCTION:
        return _lookup_failure(connection, "lookup named the wrong function")
    response = lookup.get("response")
    if not bool(_value(response, "success", False)):
        error = _value(response, "error")
        detail = str(_value(error, "message") or "request failed")
        return _lookup_failure(connection, detail)
    result = _value(response, "result")
    if not isinstance(result, Mapping) or "holder" not in result:
        return _lookup_failure(connection, "response omitted the holder field")
    holder = result.get("holder")
    if holder is None:
        return f"{_MISSING_CLAIM}; acquire one with `yoke claims work acquire`"
    if not isinstance(holder, Mapping):
        return _lookup_failure(connection, "holder response was malformed")
    try:
        matches_item = item_id_from_row(holder) == int(item_id)
    except (KeyError, TypeError, ValueError):
        matches_item = False
    if not matches_item:
        return _lookup_failure(connection, "holder named a different item")
    holder_session = str(holder.get("session_id") or "")
    if not holder_session:
        return _lookup_failure(connection, "holder omitted its session id")
    caller = session_id or str(lookup.get("caller_session_id") or "") or _session_id("")
    if not caller:
        return "ambient session identity is unavailable"
    if holder_session != caller:
        return f"work claim held by another session ({holder_session})"
    return ""


def claim_error(item_id: int, session_id: str) -> str:
    """Empty when the caller owns the item claim, else the refusal."""
    lookup = _WORK_CLAIM_LOOKUP.get()
    if lookup is not None:
        return _claim_error_from_lookup(item_id, session_id, lookup)
    response = call_dispatcher(
        function_id=_HOLDER_FUNCTION,
        target=TargetRef(kind="item", item_id=item_id),
    )
    return _claim_error_from_lookup(
        item_id,
        session_id,
        {
            "caller_session_id": _session_id(session_id),
            "connection": _active_connection_name(),
            "function_id": _HOLDER_FUNCTION,
            "response": response,
        },
    )


def claim_is_missing(error: str) -> bool:
    """Whether *error* specifically reports an unowned item."""
    return error.startswith(_MISSING_CLAIM)


def branch_needs_receipt(repo_root: str, branch: str) -> bool:
    """Whether close-out must reconstruct the pruned lane from its receipt."""
    return not git.branch_exists(repo_root, branch)


def reacquire_landed_claim(
    *,
    item_id: int,
    session_id: str,
    lane: Optional[LandedLane],
) -> tuple[Optional[LandedLane], str]:
    """Reclaim close-out authority, but only for a landing already proven.

    Whether the lane landed is decided by
    :func:`yoke_core.domain.standalone_item_merge_landed.landed_lane`, which
    reads the checkout and the durable receipt together; an absent ``lane``
    means it did not, so the claim refusal stands as the caller's own.
    """
    if lane is None:
        diagnosis = claim_error(item_id, session_id)
        if diagnosis:
            return None, diagnosis
        return None, (
            "no active worktree lane and no landing the base branch "
            "contains; merge source cannot be recovered"
        )
    caller = _session_id(session_id)
    if not caller:
        return None, "ambient session identity is unavailable"
    response = call_dispatcher(
        function_id="claims.work.acquire",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "target": {"kind": "item", "item_id": item_id},
            "reason": "Converge landed merge close-out",
        },
        actor=ActorContext(session_id=caller),
        intent="landed merge close-out recovery",
    )
    if not response.success:
        return None, _relay_error(response, "work-claim recovery failed")
    return lane, ""


def with_recorded_head(
    item: dict[str, Any],
    lane: LandedLane,
) -> dict[str, Any]:
    """Present the landing's verified lane head as the unique active lane."""
    return {
        **item,
        "worktrees": [
            {
                "state": "active",
                "branch": lane.branch,
                "commit_sha": lane.commit_sha,
            }
        ],
    }


def restore_close_out_claim(
    *,
    item: dict[str, Any],
    item_id: int,
    session_id: str,
    lane: Optional[LandedLane],
) -> tuple[dict[str, Any], str]:
    """Reclaim close-out authority when the landing outlived the work claim."""
    from yoke_core.domain import standalone_item_merge_evidence as evidence

    if not claim_error(item_id, session_id):
        return item, ""
    recovered, error = reacquire_landed_claim(
        item_id=item_id,
        session_id=session_id,
        lane=lane,
    )
    if error or recovered is None:
        if evidence.authoritative_status_is(item_id, evidence.CLOSED_OUT_STATUS):
            return item, ""
        return item, (
            error
            or "the merge is landed but close-out authority could not be "
            "recovered to finish it"
        )
    return with_recorded_head(item, recovered), ""


__all__ = [
    "bind_work_claim_lookup",
    "branch_needs_receipt",
    "claim_error",
    "claim_is_missing",
    "reacquire_landed_claim",
    "restore_close_out_claim",
    "with_recorded_head",
]
