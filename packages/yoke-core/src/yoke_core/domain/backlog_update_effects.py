"""Transactional side effects after a canonical backlog item update."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_epic_task_cascade import _cascade_epic_tasks
from yoke_core.domain.backlog_session_attribution import (
    _maybe_set_session_current_item,
)


@dataclass(frozen=True)
class UpdateEffectReceipt:
    """Post-commit work for DB effects already written atomically."""

    status_event: Optional[tuple[int, str, str, str]]
    session_id: Optional[str]
    messages: tuple[str, ...]
    path_claim_ids_to_propagate: tuple[int, ...] = ()
    terminal_holder_session_ids: tuple[str, ...] = ()


def run_transactional_update_effects(
    conn: Any,
    *,
    item_id: int,
    field: str,
    value: str,
    old_status: Optional[str],
    mutation_events: Iterable[Any],
    session_id: Optional[str],
    out: TextIO,
    status_source: Optional[str] = None,
    approval_request_id: Optional[int] = None,
    workflow_version_id: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> UpdateEffectReceipt:
    """Emit transition evidence, cascade tasks, and clean terminal claims."""
    messages: list[str] = []
    for event in mutation_events:
        if event.kind.value == "rework_incremented":
            rework_count = event.detail.get("rework_count", "")
            if rework_count:
                messages.append(
                    f"Rework detected: YOK-{item_id} rework_count → {rework_count}"
                )

    transitioned = field == "status" and bool(old_status) and old_status != value
    status_event: Optional[tuple[int, str, str, str]] = None
    if transitioned:
        from yoke_core.domain.item_status_transitions import record_item_transition

        source = status_source or os.environ.get(
            "YOKE_STATUS_SOURCE",
            "backlog-registry",
        )
        record_item_transition(
            conn,
            item_id=item_id,
            from_status=str(old_status),
            to_status=value,
            source=source,
        )
        _cascade_epic_tasks(
            conn,
            item_id,
            str(old_status),
            value,
            out,
            commit=False,
            strict=True,
        )
        status_event = (item_id, str(old_status), value, source)
        if approval_request_id is not None:
            from yoke_core.domain.approval_gate import (
                consume_lifecycle_approval,
            )

            consume_lifecycle_approval(
                conn,
                request_id=int(approval_request_id),
                item_id=item_id,
                from_stage_id=str(old_status),
                to_stage_id=value,
                workflow_version_id=int(workflow_version_id or 0),
                commit=False,
            )

    terminal_statuses: frozenset[str] = frozenset()
    terminal_holder_session_ids: tuple[str, ...] = ()
    if transitioned:
        from yoke_core.domain.item_terminal_resources import (
            release_for_terminal_transition,
            terminal_stage_ids,
        )
        from yoke_core.domain.workflow_runtime import (
            load_item_workflow_runtime,
        )

        runtime = load_item_workflow_runtime(conn, int(item_id))
        terminal_statuses = terminal_stage_ids(runtime)
        terminal_receipt = release_for_terminal_transition(
            conn,
            item_id=item_id,
            target_status=value,
            session_id=session_id,
            actor_id=actor_id,
        )
        terminal_holder_session_ids = terminal_receipt.holder_session_ids
        if terminal_receipt.document_claim_released:
            messages.append("Released the execution-document claim.")
        if terminal_receipt.ephemeral_environments_stopped:
            messages.append(
                "Stopped "
                f"{terminal_receipt.ephemeral_environments_stopped} "
                "item-bound ephemeral environment(s)."
            )
        if terminal_receipt.worktree_lanes_released:
            messages.append(
                "Released "
                f"{terminal_receipt.worktree_lanes_released} "
                "item worktree lane(s)."
            )
        if terminal_receipt.work_claims_released:
            messages.append(
                "Released "
                f"{terminal_receipt.work_claims_released} "
                "item/task work claim(s)."
            )
    path_claim_ids_to_propagate: tuple[int, ...] = ()
    if (
        field == "status"
        and value
        in {
            "cancelled",
            "stopped",
            "release",
        }
        | terminal_statuses
    ):
        cleanup_message, path_claim_ids_to_propagate = _clean_terminal_path_claims(
            conn,
            item_id=item_id,
            target_status=value,
            terminal_statuses=terminal_statuses,
        )
        if cleanup_message:
            messages.append(cleanup_message)

    if field == "status" and value == "done":
        messages.append(
            f"Done cleanup: YOK-{item_id} frozen→false, blocked→false, "
            "active worktree lanes→released"
        )
    return UpdateEffectReceipt(
        status_event=status_event,
        session_id=session_id,
        messages=tuple(messages),
        path_claim_ids_to_propagate=path_claim_ids_to_propagate,
        terminal_holder_session_ids=terminal_holder_session_ids,
    )


def run_post_commit_update_effects(
    conn: Any,
    *,
    receipt: UpdateEffectReceipt,
    out: TextIO,
) -> None:
    """Emit telemetry and best-effort attribution after the DB commit."""
    for message in receipt.messages:
        print(message, file=out)
    if receipt.status_event is None:
        return
    item_id, old_status, new_status, source = receipt.status_event
    if receipt.terminal_holder_session_ids:
        try:
            from yoke_core.domain.sessions_terminal_focus_cleanup import (
                clear_terminal_item_focuses,
            )

            clear_terminal_item_focuses(
                conn,
                item_id,
                receipt.terminal_holder_session_ids,
            )
        except Exception as exc:  # noqa: BLE001 - postcommit attribution
            conn.rollback()
            print(
                f"Advisory: terminal session focus cleanup deferred: {exc}",
                file=out,
            )
    else:
        try:
            _maybe_set_session_current_item(conn, item_id, receipt.session_id)
        except Exception as exc:  # noqa: BLE001 - postcommit attribution
            conn.rollback()
            print(
                f"Advisory: session item attribution deferred: {exc}",
                file=out,
            )
    for claim_id in receipt.path_claim_ids_to_propagate:
        try:
            from yoke_core.domain.path_claims_dependency_propagation import (
                propagate_release_unblock,
            )

            propagate_release_unblock(
                conn,
                released_claim_id=int(claim_id),
                commit=True,
            )
        except Exception as exc:  # noqa: BLE001 - recoverable downstream repair
            conn.rollback()
            print(
                "Advisory: downstream path-claim unblock deferred for "
                f"claim {claim_id}: {exc}",
                file=out,
            )
    try:
        from yoke_core.domain.item_status_transitions import (
            emit_item_status_change,
        )

        emit_item_status_change(
            item_id=item_id,
            from_status=old_status,
            to_status=new_status,
            source=source,
            out=out,
        )
    except Exception as exc:  # noqa: BLE001 - committed transition telemetry
        print(
            f"Advisory: status-change telemetry deferred: {exc}",
            file=out,
        )


def _clean_terminal_path_claims(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
    terminal_statuses: frozenset[str] = frozenset(),
) -> tuple[Optional[str], tuple[int, ...]]:
    released_claim_ids: list[int] = []
    if target_status in {"cancelled", "stopped"}:
        from yoke_core.domain.path_claims_item_hook import (
            cancel_claims_on_item_terminal as hook,
        )

        verb = "Cancelled"
        hook_kwargs = {}
    elif target_status in terminal_statuses or (
        target_status == "release"
        and (
            os.environ.get("YOKE_STATUS_SOURCE") == "done-transition"
            or os.environ.get("YOKE_CLAIM_BYPASS", "").startswith("deploy-pipeline:")
        )
    ):
        from yoke_core.domain.path_claims_item_hook_release import (
            release_claims_on_item_terminal as hook,
        )

        verb = "Released"
        hook_kwargs = {
            "terminal_statuses": terminal_statuses,
            "propagate": False,
            "released_claim_ids": released_claim_ids,
        }
    else:
        return None, ()
    count = hook(
        conn,
        item_id=item_id,
        new_status=target_status,
        commit=False,
        **hook_kwargs,
    )
    if not count:
        return None, tuple(released_claim_ids)
    return (
        (f"{verb} {count} non-terminal path claim(s) for YOK-{item_id}"),
        tuple(released_claim_ids),
    )


__all__ = [
    "UpdateEffectReceipt",
    "run_post_commit_update_effects",
    "run_transactional_update_effects",
]
