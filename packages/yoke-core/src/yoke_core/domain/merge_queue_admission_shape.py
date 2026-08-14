"""Resolving what admission control needs to know, through registered reads.

:mod:`yoke_core.domain.merge_queue_admission` decides whether a candidate may
join a train; it takes that decision over plain shapes so the policy stays
testable without a control plane. This module is where those shapes come
from: an item's non-terminal path-claim targets, whether it carries a
governed migration, and how it is linked to the items already queued.

Every read rides the registered function-call surface, so the merge boundary
relays over an https control plane exactly as it dispatches in-process.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef

from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_queue_admission import TrainCandidate, TrainContext


_NON_TERMINAL_CLAIM_STATES = ("planned", "active", "blocked")


def _dispatch_read(
    dispatch: Callable[..., Any],
    *,
    function_id: str,
    item_ref: str,
    payload: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    response = dispatch(
        function_id=function_id,
        target=TargetRef(kind="item", item_ref=item_ref),
        payload=payload,
    )
    if getattr(response, "success", False):
        result = getattr(response, "result", None)
        return (result if isinstance(result, dict) else {}), None
    error = getattr(response, "error", None)
    message = getattr(error, "message", None) or f"{function_id} failed"
    return None, f"{function_id}({item_ref}): {message}"


def candidate_shape(
    dispatch: Callable[..., Any], item_ref: str
) -> tuple[Optional[TrainCandidate], Optional[str]]:
    """Resolve one item's admission shape through registered reads."""
    claims_result, claims_err = _dispatch_read(
        dispatch,
        function_id="claims.path.list",
        item_ref=item_ref,
        payload={},
    )
    if claims_err:
        return None, claims_err
    target_ids: set[int] = set()
    for claim in (claims_result or {}).get("claims") or []:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("state") or "") not in _NON_TERMINAL_CLAIM_STATES:
            continue
        for target_id in claim.get("target_ids") or []:
            try:
                target_ids.add(int(target_id))
            except (TypeError, ValueError):
                continue
    profile_result, profile_err = _dispatch_read(
        dispatch,
        function_id="items.get.run",
        item_ref=item_ref,
        payload={"fields": ["db_mutation_profile"]},
    )
    if profile_err:
        return None, profile_err
    fields = (profile_result or {}).get("fields")
    if not isinstance(fields, dict):
        fields = {}
    raw_profile = fields.get("db_mutation_profile") or ""
    carrier = False
    if raw_profile:
        try:
            parsed = loads_text(str(raw_profile))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            carrier = str(parsed.get("state") or "none") != "none"
    return (
        TrainCandidate(
            item_ref=item_ref,
            claimed_target_ids=frozenset(target_ids),
            migration_carrier=carrier,
        ),
        None,
    )


def train_context(
    dispatch: Callable[..., Any],
    candidate_ref: str,
    member_refs: tuple[str, ...],
) -> tuple[Optional[TrainContext], Optional[str]]:
    """Resolve the queued members and how the candidate is linked to them."""
    members: list[TrainCandidate] = []
    for ref in member_refs:
        shape, err = candidate_shape(dispatch, ref)
        if err:
            return None, err
        members.append(shape)
    deps_result, deps_err = _dispatch_read(
        dispatch,
        function_id="shepherd.dependency_list.run",
        item_ref=candidate_ref,
        payload={},
    )
    if deps_err:
        return None, deps_err
    attested: set[str] = set()
    serial: set[str] = set()
    for row in (deps_result or {}).get("dependencies") or []:
        if not isinstance(row, dict):
            continue
        other = str(row.get("other_item") or "")
        if not other or other == candidate_ref:
            continue
        if str(row.get("gate_point") or "") == "coordination_only":
            attested.add(other)
        else:
            serial.add(other)
    return (
        TrainContext(
            members=tuple(members),
            coordination_attested_refs=frozenset(attested),
            serial_linked_refs=frozenset(serial),
        ),
        None,
    )


__all__ = ["candidate_shape", "train_context"]
