"""Write-side item helpers; validation lives in ``items_writes_validation``."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, instant_parameter
from yoke_core.domain.items_bulk_writes import update_item_multi as update_item_multi
from yoke_core.domain.item_field_parameters import item_field_parameter
from yoke_core.domain.items_constants import (
    CONTENT_FIELDS,
    DEFAULT_ITEM_ACTOR_ID,
    INTEGER_FIELDS,
    STRUCTURED_FIELDS,
    _map_blocked_write,
    _map_frozen_write,
    _now_utc,
)
from yoke_core.domain.items_writes_validation import (
    _WORKFLOW_BINDING_FIELDS,
    _reject_workflow_controlled_fields,
    apply_field_validators,
    check_empty_content_guard,
    check_freeze_guards,
    check_shrinkage_guard,
)
from yoke_core.domain.deployment_flow_validator import (
    require_flow_for_item_binding,
)
from yoke_core.domain.project_identity import (
    allocate_project_sequence,
    resolve_project,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def insert_item(
    item_id: int,
    title: Optional[str] = None,
    workflow: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = "medium",
    frozen: Optional[int] = 0,
    blocked: Optional[int] = 0,
    blocked_reason: Optional[str] = None,
    github_issue: Optional[str] = None,
    deployed_to: Optional[str] = None,
    body: Optional[str] = None,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    source: str = DEFAULT_ITEM_ACTOR_ID,
    project: Optional[str] = None,
    project_sequence: Optional[int] = None,
    deployment_flow: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Insert a new item.

    ``body`` is accepted but ignored: it renders from structured fields.

    ``project`` names the project the item belongs to. Unnamed, it is
    resolved from the checkout this call is standing in, and refuses when
    that answers nothing -- never this installation's own project, which
    would file the work on a backlog nobody chose.

    Raises the active database driver's error on failure.
    """
    selected_workflow = (workflow or "").strip()
    if not selected_workflow:
        raise ValueError("workflow is required")

    now = _now_utc()
    if created_at is None:
        created_at = now
    if updated_at is None:
        updated_at = now

    conn = connect(db_path)
    try:
        require_flow_for_item_binding(conn, deployment_flow, project)
        project_identity = resolve_project(conn, project or None)
        assert project_identity is not None
        from yoke_core.domain.workflow_registry import (
            resolve_current_workflow_pin,
        )

        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn,
            selected_workflow,
        )
        if status is None:
            from yoke_core.domain.workflow_runtime import load_workflow_runtime

            status = load_workflow_runtime(
                conn,
                workflow_id=workflow_id,
                workflow_version_id=workflow_version_id,
            ).stage_ids[0]
        if project_sequence is None:
            project_sequence = allocate_project_sequence(conn, project_identity.id)
        conn.execute(
            """
            INSERT INTO items (
                id, title, workflow_id, workflow_version_id,
                status, priority,
                frozen, blocked, blocked_reason,
                github_issue, deployed_to,
                created_at, updated_at, source,
                project_id, project_sequence, deployment_flow
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item_id,
                title,
                workflow_id,
                workflow_version_id,
                status,
                priority,
                frozen,
                blocked,
                blocked_reason,
                github_issue,
                deployed_to,
                item_field_parameter(conn, "created_at", created_at),
                item_field_parameter(conn, "updated_at", updated_at),
                source,
                project_identity.id,
                project_sequence,
                deployment_flow,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_item_field(
    item_id: int,
    field: str,
    value: str,
    db_path: Optional[str] = None,
) -> None:
    """Update a single non-structured field on an item.

    Handles ``frozen`` boolean mapping, ``"null"`` -> SQL NULL, and integer
    fields (frozen, id). Body and structured-field writes are
    rejected; use :func:`update_structured_field` for the latter.

    Raises ``ValueError`` for body writes and invalid fields.
    """
    if field == "body":
        raise ValueError(
            "Raw body writes are no longer supported. "
            "items.body is a rendered projection. Write to a structured field instead: "
            "spec, design_spec, technical_plan, worktree_plan, "
            "shepherd_log, shepherd_caveats, test_results, deploy_log"
        )
    _reject_workflow_controlled_fields({field})

    # Route structured fields to the dedicated function
    if field in STRUCTURED_FIELDS:
        raise ValueError(
            f"Field '{field}' is a structured field. Use update_structured_field() "
            "or the 'update-structured' CLI subcommand with --stdin or "
            "--body-file."
        )

    now = _now_utc()

    # Map frozen / blocked boolean
    if field == "frozen":
        mapped = _map_frozen_write(value)
        value = mapped  # type: ignore[assignment]
    elif field == "blocked":
        mapped = _map_blocked_write(value)
        value = mapped  # type: ignore[assignment]

    # Map "null" to None
    if value == "null":
        value = None  # type: ignore[assignment]
    elif field in INTEGER_FIELDS and value is not None:
        try:
            value = int(value)  # type: ignore[assignment]
        except (ValueError, TypeError):
            pass

    conn = connect(db_path)
    try:
        if field in _WORKFLOW_BINDING_FIELDS:
            require_flow_for_item_binding(conn, value)
            lock_item_workflow_bindings(conn, (int(item_id),))
        conn.execute(
            f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
            (
                item_field_parameter(conn, field, value),
                instant_parameter(conn, now),
                item_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_structured_field(
    item_id: int,
    field: str,
    content: str,
    force: bool = False,
    source: str = "",
    db_path: Optional[str] = None,
) -> None:
    """Update a structured text field with safety guards.

    Safety nets:
    - **Empty-content guard:** refuses to overwrite non-empty field with empty.
    - **Shrinkage guard:** refuses writes where new content is <50% of existing
      line count when existing has 10+ lines (unless *force* is True).

    Also tracks ``spec_updated_at`` / ``spec_updated_by`` for content-bearing
    fields.

    Raises ``ValueError`` for invalid field, empty-content refusal, or
    shrinkage refusal. Raises ``sqlite3.Error`` on DB failure.
    """
    if field not in STRUCTURED_FIELDS:
        raise ValueError(f"Invalid structured field: {field}")

    content = apply_field_validators(field, content)
    has_content = bool(content and content.strip())

    now = _now_utc()

    conn = connect(db_path)
    try:
        check_empty_content_guard(conn, field, item_id, has_content)
        check_shrinkage_guard(conn, field, item_id, content, force, has_content)
        check_freeze_guards(conn, field, item_id, content, has_content)

        # Build update with optional spec tracking
        if field in CONTENT_FIELDS and source:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s, "
                f"spec_updated_at = %s, spec_updated_by = %s WHERE id = %s",
                (
                    content,
                    instant_parameter(conn, now),
                    instant_parameter(conn, now),
                    source,
                    item_id,
                ),
            )
        elif field in CONTENT_FIELDS:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s, "
                f"spec_updated_at = %s WHERE id = %s",
                (
                    content,
                    instant_parameter(conn, now),
                    instant_parameter(conn, now),
                    item_id,
                ),
            )
        else:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
                (content, instant_parameter(conn, now), item_id),
            )
        conn.commit()
    except ValueError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
