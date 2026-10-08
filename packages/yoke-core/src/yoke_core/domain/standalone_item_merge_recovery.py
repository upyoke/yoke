"""Recover a landed standalone merge whose work claim was reclaimed."""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.standalone_item_merge_landed import LandedLane

_MISSING_CLAIM = "no live work claim on this item"
_UNRECOVERED_LANE = (
    "no active worktree lane and no landing the base branch "
    "contains; merge source cannot be recovered"
)
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


def record_resolved_item(item: Mapping[str, Any]) -> None:
    """Bind an older holder's join key to the detail response already read."""
    lookup = _WORK_CLAIM_LOOKUP.get()
    if lookup is not None:
        _WORK_CLAIM_LOOKUP.set({**lookup, "resolved_item": dict(item)})


def _holder_matches_item(holder, expected_ref, lookup) -> bool:
    scope = holder.get("scope") or {}
    if not isinstance(scope, Mapping):
        return False
    public_ref = scope.get("public_ref") or holder.get("public_ref")
    if public_ref is not None:
        return str(public_ref) == expected_ref
    # Released servers return the owned key. It is evidence only when the
    # same operation's item-detail read supplies its complete public ref.
    item = lookup.get("resolved_item") or {}
    owned_id = scope.get("item_id", holder.get("item_id"))
    return (
        isinstance(item, Mapping)
        and item.get("public_ref") == expected_ref
        and lookup.get("requested_public_ref", expected_ref) == expected_ref
        and isinstance(owned_id, int)
        and not isinstance(owned_id, bool)
        and owned_id > 0
        and item.get("id") == owned_id
    )


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
        matches_item = _holder_matches_item(
            holder, str(public_item_target(item_id).public_ref), lookup
        )
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
        target=public_item_target(item_id),
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


def missing_lane_refusal(item_id: Any, item: Optional[Mapping[str, Any]]) -> str:
    """Name the laneless route when evidence proves it; otherwise the gap."""
    if not isinstance(item, Mapping):
        return _UNRECOVERED_LANE
    workflow_id = str((item.get("workflow") or {}).get("id") or "")
    from yoke_core.domain.standalone_item_merge_lane import active_lanes

    if workflow_id != "dash" or active_lanes(dict(item)):
        return _UNRECOVERED_LANE
    try:
        from yoke_core.domain.standalone_item_merge_evidence import recorded

        row = recorded(item_id)
        no_changes = row.get("no_changes") if isinstance(row, dict) else False
    except Exception as exc:  # noqa: BLE001 - an unread record must not attest
        return (
            "no active worktree lane; persisted Execution Evidence could "
            f"not be read ({exc}). An absent worktree does not attest "
            "no_changes and is not a Git landing to recover. Re-run "
            "`yoke merge item` once that read succeeds."
        )
    from yoke_core.domain.dash_execution import proved_laneless_no_change

    if not proved_laneless_no_change(
        workflow_id=workflow_id,
        no_changes=no_changes,
        active_worktree_present=False,
    ):
        return _UNRECOVERED_LANE
    return _laneless_route(dict(item))


def _laneless_route(item: Mapping[str, Any]) -> str:
    from yoke_core.domain.merge_review_readiness import pinned_workflow_for_item
    from yoke_core.domain.workflow_declared_transitions import (
        declared_next_stage_ids,
    )

    public_ref = str(item.get("public_ref") or item.get("id") or "")
    status = str(item.get("status") or "")
    base = (
        "laneless no-change close-out: persisted Execution Evidence "
        "records no_changes and this Dash has no active worktree, so "
        "there is no Git landing to recover"
    )
    workflow, error = pinned_workflow_for_item(dict(item))
    if workflow is None:
        return (
            f"{base}. The pinned workflow could not be read ({error}). "
            "workflow_next_stage_ambiguous: this merge does not guess a "
            "stage or transition. Resolve the workflow read, then advance "
            "the unique forward edge with `yoke lifecycle transition`."
        )
    targets = tuple(
        stage_id
        for stage_id in declared_next_stage_ids(workflow, status)
        if workflow.is_forward_transition(status, stage_id)
    )
    named = f"{workflow.workflow_id}@{workflow.version}"
    if len(targets) != 1:
        listed = ", ".join(targets) or "none"
        return (
            f"{base}. workflow_next_stage_ambiguous: {named} at "
            f"{status!r} declares {len(targets)} forward edges ({listed}). "
            "Repair or select the declared route. This merge does not "
            "guess a stage or transition."
        )
    target = targets[0]
    return (
        f"{base}. Advance {named} from {status!r} to {target!r} with "
        f"`yoke lifecycle transition {public_ref} --from {status} --to "
        f'{target} --reason "Laneless attestation recorded; advancing '
        'the declared stage"`. This merge does not transition. Evidence, '
        "QA, approval, claim, and delivery gates still apply on that "
        "transition. `yoke merge item --no-changes` is only for a lane "
        "that already exists."
    )


def branch_needs_receipt(repo_root: str, branch: str) -> bool:
    """Whether close-out must reconstruct the pruned lane from its receipt."""
    return not git.branch_exists(repo_root, branch)


def reacquire_landed_claim(
    *,
    item_id: int,
    session_id: str,
    lane: Optional[LandedLane],
    item: Optional[Mapping[str, Any]] = None,
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
        return None, missing_lane_refusal(item_id, item)
    caller = _session_id(session_id)
    if not caller:
        return None, "ambient session identity is unavailable"
    response = call_dispatcher(
        function_id="claims.work.acquire",
        target=public_item_target(item_id),
        payload={
            "target": {"kind": "item"},
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
    "missing_lane_refusal",
    "reacquire_landed_claim",
    "record_resolved_item",
    "restore_close_out_claim",
    "with_recorded_head",
]
