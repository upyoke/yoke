"""Item-facing path-claim registration on-ramp.

Item create / update / refine surfaces use this module to resolve
project-relative paths, default the actor, and call the lifecycle
``register`` boundary. The lifecycle module owns overlap classification;
this sister module owns lookup and event hand-off so ``path_claims.py``
stays below the file-budget cap.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain.path_claims import register as register_claim
from yoke_core.domain.path_claims_registration_context import (
    DefaultActorUnavailable,
    ItemHasNoProject,
    ItemNotFound,
    PathClaimRegistrationError,
    fetch_item_project_id as _fetch_item_project_id,
    parameter_marker as _p,
    resolve_registration_actor as _resolve_actor_for_caller,
)
from yoke_core.domain.path_claims_register_symlink import (
    emit_decisions as _emit_symlink_decisions,
    expand_for_registration as _expand_symlinks_for_registration,
)
from yoke_core.domain.path_claims_resolve import (
    EmptyPathSet,
    UnknownPathTargets,
    resolve_paths_to_target_ids,
)


def register_for_item(
    conn: Any,
    *,
    item_id: int,
    integration_target: str,
    paths: Iterable[str],
    upstream_claim_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    session_id: Optional[str] = None,
    mode: str = "exclusive",
    exception_reason: Optional[str] = None,
    allow_planned: bool = False,
    directory_paths: Optional[Iterable[str]] = None,
    tentative_paths: Optional[Iterable[str]] = None,
    task_num: Optional[int] = None,
    commit: bool = True,
    emit_events: bool = True,
) -> int:
    """Register a planned path claim for ``item_id`` and return its id."""
    from yoke_core.domain import path_claims_events as _events
    from yoke_core.domain.path_claims import (
        InvalidTargetSet,
        InvalidWorkflowBinding,
        PathClaimError,
        get_claim,
    )
    from yoke_core.domain.workflow_item_binding_lock import (
        lock_item_workflow_bindings,
    )
    from yoke_core.domain.workflow_item_binding_validation import (
        WorkflowItemBindingError,
        validate_item_path_claim_scope,
    )

    lock_item_workflow_bindings(conn, (int(item_id),))
    project_id = _fetch_item_project_id(conn, item_id)
    try:
        validate_item_path_claim_scope(
            conn,
            int(item_id),
            task_num=task_num,
        )
    except WorkflowItemBindingError as exc:
        raise InvalidWorkflowBinding(str(exc)) from exc
    path_list, symlink_decisions = _expand_symlinks_for_registration(
        conn,
        project_id,
        paths,
    )

    def _emit_symlinks(cid):
        _emit_symlink_decisions(
            conn,
            claim_id=cid,
            project_id=project_id,
            item_id=item_id,
            session_id=session_id,
            decisions=symlink_decisions,
        )

    resolved_upstream_claim_id: Optional[int] = None
    try:
        if mode == "exception":
            if path_list:
                raise InvalidTargetSet(
                    "mode='exception' must not declare paths; exceptions "
                    "record a no-claim justification, not coverage"
                )
            target_ids = []
        elif allow_planned:
            from yoke_core.domain.path_claims_resolve import (
                resolve_or_plan_paths_to_target_ids,
            )  # noqa: E501

            target_ids = resolve_or_plan_paths_to_target_ids(
                conn,
                project_id,
                path_list,
                item_id=item_id,
                session_id=session_id,
                directory_paths=(list(directory_paths) if directory_paths else None),
                tentative_paths=(list(tentative_paths) if tentative_paths else None),
            )
        else:
            target_ids = resolve_paths_to_target_ids(
                conn,
                project_id,
                path_list,
            )
        resolved_actor = _resolve_actor_for_caller(
            conn,
            actor_id,
            session_id=session_id,
        )
        if mode != "exception" and target_ids:
            from yoke_core.domain.path_claims_register_reconcile import (
                cancel_superseded_exceptions,
                reuse_existing_concrete_claim,
            )

            claim_id = reuse_existing_concrete_claim(
                conn,
                item_id=item_id,
                integration_target=integration_target,
                target_ids=target_ids,
                project_id=project_id,
                commit=commit,
                emit_event=emit_events,
            )
            if claim_id is not None:
                if allow_planned:
                    _backfill_planned_claim_id(conn, target_ids, claim_id)
                cancel_superseded_exceptions(
                    conn,
                    item_id=item_id,
                    integration_target=integration_target,
                    replacement_claim_id=claim_id,
                    project_id=project_id,
                    task_num=task_num,
                    commit=commit,
                    emit_event=emit_events,
                )
                if emit_events:
                    _emit_symlinks(claim_id)
                return claim_id
        if mode != "exception" and target_ids and upstream_claim_id is None:
            from yoke_core.domain.path_claims_dependency_resolver import (
                auto_resolve_upstream,
            )

            resolved_upstream_claim_id = auto_resolve_upstream(
                conn,
                item_id=item_id,
                integration_target=integration_target,
                paths=path_list,
                allow_planned=allow_planned,
                directory_paths=(list(directory_paths) if directory_paths else None),
            )
        claim_id = register_claim(
            conn,
            actor_id=resolved_actor,
            integration_target=integration_target,
            target_ids=target_ids,
            mode=mode,
            session_id=session_id,
            item_id=item_id,
            upstream_claim_id=upstream_claim_id,
            exception_reason=exception_reason,
            candidate_item_id=item_id,
            task_num=task_num,
            commit=commit,
        )
        if resolved_upstream_claim_id is not None:
            p = _p(conn)
            conn.execute(
                f"UPDATE path_claims SET blocked_reason = {p} "
                f"WHERE id = {p} AND state = 'blocked'",
                (
                    "serial-via-dependency on path_claims.id="
                    f"{resolved_upstream_claim_id}",
                    claim_id,
                ),
            )
            if commit:
                conn.commit()
        if mode != "exception" and allow_planned and target_ids:
            _backfill_planned_claim_id(conn, target_ids, claim_id)
        if mode != "exception" and target_ids:
            from yoke_core.domain.path_claims_register_reconcile import (
                cancel_superseded_exceptions,
            )

            cancel_superseded_exceptions(
                conn,
                item_id=item_id,
                integration_target=integration_target,
                replacement_claim_id=claim_id,
                project_id=project_id,
                task_num=task_num,
                commit=commit,
                emit_event=emit_events,
            )
    except PathClaimError as exc:
        if emit_events:
            _events.emit_registration_blocked(
                conn=conn,
                item_id=item_id,
                integration_target=integration_target,
                reason=str(exc),
                blocking_claim_id=resolved_upstream_claim_id,
                project=project_id,
                session_id=session_id,
            )
        raise
    if emit_events:
        _events.emit_registered(
            conn=conn,
            claim=get_claim(conn, claim_id),
            project=project_id,
        )
        _emit_symlinks(claim_id)
    return claim_id


def _backfill_planned_claim_id(
    conn: Any,
    target_ids: list[int],
    claim_id: int,
) -> None:
    """Backfill claim attribution on planned rows minted before claim insert."""
    if not target_ids:
        return
    p = _p(conn)
    placeholders = ",".join(p for _ in target_ids)
    conn.execute(
        f"UPDATE path_targets "
        f"SET planned_by_claim_id = {p} "
        f"WHERE id IN ({placeholders}) "
        f"AND materialization_state = 'planned' "
        f"AND planned_by_claim_id IS NULL",
        (claim_id, *target_ids),
    )


def activate_with_events(
    conn: Any,
    *,
    claim_id: int,
    base_commit_sha: str,
    upstream_claim_id: Optional[int] = None,
) -> None:
    """Activate a claim and emit ``PathClaimActivated`` / ``...Blocked``.

    Thin wrapper around :func:`yoke_core.domain.path_claims.activate`
    so the worktree-create surface (and any future direct caller) does
    not have to re-author the emission boilerplate. The activation
    semantics are unchanged; only the event side effect is added.

    ``base_commit_sha`` is a caller-supplied parameter and not
    auto-derived inside the wrapper. The contract is that callers
    resolve the integration-target head SHA BEFORE calling this
    function — that records "what was the integration target's tip
    when activation ran?" on the claim row so downstream stale-base /
    age-hint checks can compare against the activation-time state.
    """
    from yoke_core.domain import path_claims_events as _events
    from yoke_core.domain.path_claims import (
        PathClaimError,
        activate as _activate,
        get_claim,
    )

    pre = get_claim(conn, claim_id)
    project_id: Optional[int] = None
    item_id_raw = pre.get("owner_item_id")
    if item_id_raw is not None:
        try:
            project_id = _fetch_item_project_id(conn, int(item_id_raw))
        except (ItemNotFound, ItemHasNoProject):
            project_id = None
    try:
        _activate(
            conn,
            claim_id=claim_id,
            base_commit_sha=base_commit_sha,
            upstream_claim_id=upstream_claim_id,
        )
    except PathClaimError as exc:
        _events.emit_activation_blocked(
            conn=conn,
            claim_id=claim_id,
            integration_target=pre.get("integration_target"),
            reason=str(exc),
            item_id=pre.get("owner_item_id"),
            project=project_id,
            session_id=pre.get("registered_by_session_id"),
        )
        raise
    _events.emit_activated(
        conn=conn,
        claim=get_claim(conn, claim_id),
        project=project_id,
    )


__all__ = [
    "DefaultActorUnavailable",
    "EmptyPathSet",
    "ItemHasNoProject",
    "ItemNotFound",
    "PathClaimRegistrationError",
    "UnknownPathTargets",
    "activate_with_events",
    "register_for_item",
]
