"""Backlog create operation — `execute_create` validates a new item via
the mutation layer, allocates a numeric ID, INSERTs the row, optionally
records session attribution, and triggers the GitHub sync. Honors
`dry_run` for preview-only flows.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Mapping, Optional, TextIO

from . import db_backend
from yoke_core.domain.actors import validate_actor_id
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    _assert_write_db_ready,
    _get_next_id,
    _now_iso,
    _resolve_write_db_path,
)
from yoke_core.domain.project_identity import (
    allocate_project_sequence,
    checkout_project_context,
    render_item_ref,
    resolve_project,
)
from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.backlog_item_db_writes import _insert_item
from yoke_core.domain.backlog_session_attribution import (
    record_touched_item,
)
from yoke_core.domain.item_entry_surface import enforce_item_entry_allowed


class SourceActorResolutionError(Exception):
    """Raised when the writer cannot resolve a valid actor id for ``items.source``.

    Three failure modes share this class so callers see one rejection
    surface: (a) an explicit ``source`` argument that is not a numeric
    actor-id token (a mechanism label such as ``user`` / ``bug`` /
    ``simulation``), (b) an explicit ``source`` whose numeric id does
    not exist in ``actors``, and (c) no source given and the calling
    session has no bound actor. Each carries a one-line message naming
    the offending value so the operator's first move is to pass the
    right actor or fix session registration, not chase the helper.
    """


def _resolve_session_source_actor(conn: Any, session_id: Optional[str]) -> int:
    """Resolve ``items.source`` from the calling session's bound actor.

    Actor identity is session/auth-bound: the explicit ``session_id``
    argument (else the ambient session) maps to
    ``harness_sessions.actor_id``. Fails closed with
    :class:`SourceActorResolutionError` when no actor resolves — the
    writer contract is that the legacy text default ``'user'`` must
    never fire on the production INSERT path.
    """
    from yoke_core.domain.path_claims_actor_resolution import (
        ActorResolutionUnavailable,
        resolve_actor_for_caller,
    )

    try:
        return resolve_actor_for_caller(conn, None, session_id=session_id)
    except ActorResolutionUnavailable as exc:
        raise SourceActorResolutionError(
            f"cannot resolve a source actor for the new item: {exc}. "
            "Pass an explicit numeric --source actor id or create the "
            "item from a registered harness session."
        ) from exc


def _coerce_explicit_source(conn: Any, source: str) -> int:
    """Validate an operator-supplied ``source`` argument as an actor id.

    Returns the integer actor id. Raises
    :class:`SourceActorResolutionError` for non-numeric values
    (mechanism labels such as ``user`` / ``bug`` / ``simulation``) and
    for numeric values that do not match any ``actors`` row.
    """
    text = source.strip()
    try:
        actor_id = int(text)
    except ValueError as exc:
        raise SourceActorResolutionError(
            f"items.source must be a numeric actor id, got {source!r}; "
            "mechanism labels are no longer accepted on the write path"
        ) from exc
    if not validate_actor_id(conn, actor_id):
        raise SourceActorResolutionError(f"items.source={actor_id} does not match any actors row")
    return actor_id


def execute_create(
    title: str,
    workflow: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None,
    deployment_flow: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    owner: Optional[str] = None,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    entry_surface: Optional[str] = None,
    instruction: Optional[str] = None,
    workflow_posture: Optional[Mapping[str, Any]] = None,
    out: TextIO = sys.stdout,
) -> dict:
    """Full item creation: validate → INSERT → md gen → GitHub sync.

    Returns a result dict with 'success', 'item_id', 'error', etc.

    ``workflow`` is required because the registry has no implicit selection.
    Persistent production creates require a typed entry surface allowed by
    the selected workflow version.
    """
    from yoke_core.domain import mutations

    if not workflow or not workflow.strip():
        return {"success": False, "error": "workflow is required"}

    if project is None:
        project = checkout_project_context()

    # Validate via mutation layer
    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)

    conn = connect(db_path)
    try:
        try:
            if source is None:
                source_actor_id = _resolve_session_source_actor(conn, session_id)
            else:
                source_actor_id = _coerce_explicit_source(conn, source)
            if owner is None:
                owner_actor_id = source_actor_id
            else:
                owner_actor_id = _coerce_explicit_source(conn, owner)
        except SourceActorResolutionError as exc:
            return {"success": False, "error": str(exc)}

        source_token = str(source_actor_id)
        owner_token = str(owner_actor_id)

        from yoke_core.domain.deployment_flow_validator import (
            normalize_deployment_flow_value,
            validate_and_lookup_flow_project,
        )

        deployment_flow = normalize_deployment_flow_value(deployment_flow)
        project_identity = resolve_project(conn, project)
        assert project_identity is not None
        flow_project, flow_err = validate_and_lookup_flow_project(conn, deployment_flow, project)
        if flow_err:
            return {"success": False, "error": flow_err}

        if priority is None:
            from yoke_core.domain.project_settings import get_project_str_for_id

            priority = get_project_str_for_id(
                project_identity.id,
                "default_priority",
            )

        from yoke_core.domain.workflow_registry import (
            resolve_current_workflow_pin,
        )

        from yoke_core.domain.workflow_runtime import load_workflow_runtime

        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn,
            workflow,
        )
        workflow_runtime = load_workflow_runtime(
            conn,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
        )
        intake_block = enforce_item_entry_allowed(
            workflow=workflow_runtime,
            entry_surface=entry_surface,
            dry_run=dry_run,
            db_path=db_path,
        )
        if intake_block:
            return {"success": False, "error": intake_block}
        clean_instruction = None if instruction is None else str(instruction).strip()
        if entry_surface == "web_form" and not clean_instruction:
            return {
                "success": False,
                "error": "web-form item creation requires an instruction",
            }
        from yoke_core.domain.item_posture_validation import (
            ItemPostureError,
            validate_item_posture,
        )

        try:
            normalized_posture = validate_item_posture(
                conn,
                definition=workflow_runtime.definition,
                project_id=project_identity.id,
                posture=workflow_posture,
            )
        except (ItemPostureError, LookupError) as exc:
            return {"success": False, "error": str(exc)}

        result = mutations.prepare_create(
            title=title,
            workflow=workflow_runtime,
            priority=priority,
            project=project,
            deployment_flow=deployment_flow,
            flow_project=flow_project,
            status=status,
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error or "Unknown validation error",
            }

        if dry_run:
            next_id = _get_next_id(conn)
            next_sequence = allocate_project_sequence(conn, project_identity.id)
            print(
                f"[DRY-RUN] Would create: {project_identity.public_item_prefix}-{next_sequence}",
                file=out,
            )
            print(f"[DRY-RUN]   Title: {title}", file=out)
            print(
                f"[DRY-RUN]   Workflow: {workflow_id} (version row {workflow_version_id})",
                file=out,
            )
            print(
                f"[DRY-RUN]   Status: {status or workflow_runtime.stage_ids[0]}",
                file=out,
            )
            print(f"[DRY-RUN]   Priority: {priority}", file=out)
            print(f"[DRY-RUN]   Project: {project}", file=out)
            if deployment_flow:
                print(f"[DRY-RUN]   Deployment Flow: {deployment_flow}", file=out)
            print(f"[DRY-RUN]   Source actor: {source_token}", file=out)
            print(f"[DRY-RUN]   Owner actor: {owner_token}", file=out)
            print(
                "[DRY-RUN] No files created, DB not modified, GitHub not synced.",
                file=out,
            )
            return {"success": True, "item_id": next_id, "dry_run": True}

        # INSERT with retry on UNIQUE constraint violation
        now = _now_iso()
        body = f"# {title}\n"
        max_retries = 3

        for attempt in range(max_retries):
            current_id = _get_next_id(conn)
            current_sequence = allocate_project_sequence(conn, project_identity.id)
            try:
                _insert_item(
                    conn,
                    current_id,
                    title,
                    status or workflow_runtime.stage_ids[0],
                    priority,
                    0,
                    None,
                    None,
                    body,
                    now,
                    now,
                    source_token,
                    project_identity.id,
                    current_sequence,
                    deployment_flow,
                    owner=owner_token,
                    workflow_id=workflow_id,
                    workflow_version_id=workflow_version_id,
                    instruction=clean_instruction,
                    workflow_posture=normalized_posture,
                    commit=False,
                )
                from yoke_core.domain.item_posture_bindings import (
                    bind_item_posture_on_create,
                )

                bind_item_posture_on_create(
                    conn,
                    item_id=current_id,
                    definition=workflow_runtime.definition,
                    posture=normalized_posture,
                    actor_id=source_actor_id,
                    commit=False,
                )
                conn.commit()
                break
            except db_backend.integrity_error_types(conn) as exc:
                conn.rollback()
                if "UNIQUE constraint" in str(exc) and attempt < max_retries - 1:
                    time.sleep(0.1)
                    continue
                raise
            except Exception:
                conn.rollback()
                raise

        record_touched_item(conn, current_id, session_id)

        public_ref = render_item_ref(conn, current_id)
        print(f"Created: {public_ref}", file=out)

        # Body completeness warning
        title_threshold = len(f"# {title}") + 4
        body_len = len(body)
        if not clean_instruction and body_len <= title_threshold:
            print("", file=out)
            print(f"WARNING: {public_ref} created with no body content.", file=out)
            print(
                "Cold-start sessions need full context: problem, fix plan, acceptance criteria.",
                file=out,
            )
            print(
                f"Use: printf '%s' \"$content\" | yoke items structured-field replace {public_ref} --field spec --stdin",
                file=out,
            )
            print("", file=out)

        # GitHub sync
        _rendering._sync_item(current_id, out)

    finally:
        conn.close()

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)

    return {"success": True, "item_id": current_id, "public_ref": public_ref}


__all__ = [
    "SourceActorResolutionError",
    "execute_create",
]
