"""Backlog create operation — `execute_create` validates a new item via
the mutation layer, allocates a numeric ID, INSERTs the row, optionally
records session attribution, and triggers the GitHub sync. Honors
`dry_run` for preview-only flows.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Optional, TextIO

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
    _maybe_set_session_current_item,
)
from yoke_core.domain.ticket_intake_provenance import (
    enforce_public_create_allowed,
)


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


def _coerce_explicit_source(
    conn: Any, source: str
) -> int:
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
        raise SourceActorResolutionError(
            f"items.source={actor_id} does not match any actors row"
        )
    return actor_id


def execute_create(
    title: str,
    item_type: str,
    priority: Optional[str] = None,
    project: Optional[str] = None,
    deployment_flow: Optional[str] = None,
    status: str = "idea",
    source: Optional[str] = None,
    owner: Optional[str] = None,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    provenance: Optional[str] = None,
    out: TextIO = sys.stdout,
) -> dict:
    """Full item creation: validate → INSERT → md gen → GitHub sync.

    Returns a result dict with 'success', 'item_id', 'error', etc.

    The ``provenance`` keyword carries the sanctioned-idea-intake
    signal (``"idea"``) when the call originates from ``/yoke idea``.
    Direct production creates without idea provenance fail closed with
    a recovery hint that names ``/yoke idea``. Dry-run and
    test-isolated DB targets bypass the gate.
    """
    from yoke_core.domain import mutations

    if project is None:
        project = checkout_project_context()

    # Validate via mutation layer
    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)

    intake_block = enforce_public_create_allowed(
        provenance=provenance, dry_run=dry_run, db_path=db_path,
    )
    if intake_block:
        return {"success": False, "error": intake_block}
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
        flow_project, flow_err = validate_and_lookup_flow_project(
            conn, deployment_flow, project
        )
        if flow_err:
            return {"success": False, "error": flow_err}

        if priority is None:
            from yoke_core.domain.project_settings import get_project_str_for_id

            priority = get_project_str_for_id(
                project_identity.id, "default_priority",
            )

        result = mutations.prepare_create(
            title=title,
            item_type=item_type,
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
                f"[DRY-RUN] Would create: "
                f"{project_identity.public_item_prefix}-{next_sequence}",
                file=out,
            )
            print(f"[DRY-RUN]   Title: {title}", file=out)
            print(f"[DRY-RUN]   Type: {item_type}", file=out)
            print(f"[DRY-RUN]   Status: {status}", file=out)
            print(f"[DRY-RUN]   Priority: {priority}", file=out)
            print(f"[DRY-RUN]   Project: {project}", file=out)
            if deployment_flow:
                print(f"[DRY-RUN]   Deployment Flow: {deployment_flow}", file=out)
            print(f"[DRY-RUN]   Source actor: {source_token}", file=out)
            print(f"[DRY-RUN]   Owner actor: {owner_token}", file=out)
            print("[DRY-RUN] No files created, DB not modified, GitHub not synced.", file=out)
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
                    conn, current_id, title, item_type, status, priority,
                    "accelerated", 0, 0,
                    None, None, None,
                    body, now, now, source_token,
                    project_identity.id, current_sequence, deployment_flow,
                    owner=owner_token,
                )
                break
            except db_backend.integrity_error_types(conn) as exc:
                if "UNIQUE constraint" in str(exc) and attempt < max_retries - 1:
                    time.sleep(0.1)
                    continue
                raise

        _maybe_set_session_current_item(conn, current_id, session_id)

        item_ref = render_item_ref(conn, current_id)
        print(f"Created: {item_ref}", file=out)

        # Body completeness warning
        title_threshold = len(f"# {title}") + 4
        body_len = len(body)
        if body_len <= title_threshold:
            print("", file=out)
            print(f"WARNING: YOK-{current_id} created with no body content.", file=out)
            print("Cold-start sessions need full context: problem, fix plan, acceptance criteria.", file=out)
            print(
                f"Use: printf '%s' \"$content\" | python3 -m yoke_core.cli.db_router "
                f"items update {current_id} spec --stdin",
                file=out,
            )
            print("", file=out)

        # GitHub sync
        _rendering._sync_item(current_id, out)

    finally:
        conn.close()

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)

    return {"success": True, "item_id": current_id, "item_ref": item_ref}


__all__ = [
    "SourceActorResolutionError",
    "execute_create",
]
