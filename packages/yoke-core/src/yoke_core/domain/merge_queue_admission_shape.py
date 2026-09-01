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
from yoke_contracts.public_ref import format_item_ref

from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.merge_preflight_github_lock_retry import (
    call_with_machine_lock_retry,
)
from yoke_core.domain.merge_queue_admission import TrainCandidate, TrainContext


_NON_TERMINAL_CLAIM_STATES = ("planned", "active", "blocked")


def _sql_literal(value: str) -> str:
    """Quote one stored identifier for the read-only SQL adapter."""
    return "'" + str(value).replace("'", "''") + "'"


def _member_item_refs(
    dispatch: Callable[..., Any],
    member_branches: tuple[str, ...],
    project: Optional[str],
) -> tuple[dict[str, str], Optional[str]]:
    """Map queued branch names to public refs through item worktree rows."""
    branches = tuple(dict.fromkeys(ref for ref in member_branches if ref))
    if not branches:
        return {}, None
    branch_literals = ", ".join(_sql_literal(branch) for branch in branches)
    project_clause = f" AND p.slug = {_sql_literal(project)}" if project else ""
    sql = (
        "SELECT iw.branch, i.id AS item_id, p.slug AS project_slug, "
        "p.public_item_prefix, i.project_sequence "
        "FROM item_worktrees iw "
        "JOIN items i ON i.id = iw.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE iw.branch IN ({branch_literals}){project_clause} "
        "ORDER BY iw.branch, "
        "CASE WHEN iw.state = 'active' THEN 0 ELSE 1 END, iw.id DESC"
    )
    response = call_with_machine_lock_retry(
        lambda: dispatch(
            function_id=DB_READ_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"sql": sql, "row_cap": 100},
        )
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        message = getattr(error, "message", None) or "lane lookup failed"
        return {}, f"{DB_READ_FUNCTION_ID}: {message}"
    result = getattr(response, "result", None) or {}
    if result.get("truncated"):
        return {}, "queued lane lookup exceeded the registered read row cap"
    columns = list(result.get("columns") or [])
    refs: dict[str, str] = {}
    for row in result.get("rows") or []:
        values = row if isinstance(row, dict) else dict(zip(columns, row))
        branch = str(values.get("branch") or "")
        if not branch or branch in refs:
            continue
        try:
            item_id = int(values.get("item_id"))
        except (TypeError, ValueError):
            continue
        refs[branch] = format_item_ref(
            values.get("project_slug"),
            values.get("public_item_prefix"),
            values.get("project_sequence"),
            item_id=item_id,
        )
    return refs, None


def _dispatch_read(
    dispatch: Callable[..., Any],
    *,
    function_id: str,
    public_ref: str,
    payload: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    response = call_with_machine_lock_retry(
        lambda: dispatch(
            function_id=function_id,
            target=TargetRef(kind="item", public_ref=public_ref),
            payload=payload,
        )
    )
    if getattr(response, "success", False):
        result = getattr(response, "result", None)
        return (result if isinstance(result, dict) else {}), None
    error = getattr(response, "error", None)
    message = getattr(error, "message", None) or f"{function_id} failed"
    return None, f"{function_id}({public_ref}): {message}"


def candidate_shape(
    dispatch: Callable[..., Any], public_ref: str
) -> tuple[Optional[TrainCandidate], Optional[str]]:
    """Resolve one item's admission shape through registered reads."""
    claims_result, claims_err = _dispatch_read(
        dispatch,
        function_id="claims.path.list",
        public_ref=public_ref,
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
        public_ref=public_ref,
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
            public_ref=public_ref,
            claimed_target_ids=frozenset(target_ids),
            migration_carrier=carrier,
        ),
        None,
    )


def train_context(
    dispatch: Callable[..., Any],
    candidate_ref: str,
    member_refs: tuple[str, ...],
    project: Optional[str] = "",
) -> tuple[Optional[TrainContext], Optional[str]]:
    """Resolve the queued members and how the candidate is linked to them."""
    resolved_refs, resolution_err = _member_item_refs(
        dispatch,
        member_refs,
        project,
    )
    if resolution_err:
        return None, resolution_err
    members: list[TrainCandidate] = []
    notes: list[str] = []
    for branch in member_refs:
        ref = resolved_refs.get(branch)
        if ref is None:
            notes.append(
                f"queued branch {branch!r} has no registered item worktree "
                "lane; skipped because it is not a Yoke item"
            )
            continue
        shape, err = candidate_shape(dispatch, ref)
        if err:
            return None, err
        members.append(shape)
    deps_result, deps_err = _dispatch_read(
        dispatch,
        function_id="items.dependency.list",
        public_ref=candidate_ref,
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
            notes=tuple(notes),
        ),
        None,
    )


__all__ = ["candidate_shape", "train_context"]
