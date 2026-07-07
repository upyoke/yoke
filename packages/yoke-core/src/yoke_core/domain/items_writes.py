"""Write-side helpers for the ``items`` table.

Owns ``insert_item``, ``update_item_field``, ``update_item_multi``, and
``update_structured_field``. Validation, content normalization, and
freeze-immutability checks live in
:mod:`yoke_core.domain.items_writes_validation` to keep this module
small.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain.db_helpers import connect
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
    apply_field_validators,
    check_empty_content_guard,
    check_freeze_guards,
    check_shrinkage_guard,
)
from yoke_core.domain.project_identity import (
    allocate_project_sequence,
    resolve_project,
)

def insert_item(
    item_id: int,
    title: Optional[str] = None,
    item_type: Optional[str] = "issue",
    status: Optional[str] = "idea",
    priority: Optional[str] = "medium",
    flow: Optional[str] = None,
    rework_count: Optional[int] = 0,
    frozen: Optional[int] = 0,
    blocked: Optional[int] = 0,
    blocked_reason: Optional[str] = None,
    github_issue: Optional[str] = None,
    deployed_to: Optional[str] = None,
    worktree: Optional[str] = None,
    body: Optional[str] = None,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    source: str = DEFAULT_ITEM_ACTOR_ID,
    project: Optional[str] = "yoke",
    project_sequence: Optional[int] = None,
    deployment_flow: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Insert a new item.

    Uses parameterised INSERT to safely handle multi-line content. The ``body``
    parameter is accepted by the API but ignored because ``items.body`` is a
    rendered projection of structured fields.

    Raises the active database driver's error on failure.
    """
    now = _now_utc()
    if created_at is None:
        created_at = now
    if updated_at is None:
        updated_at = now

    conn = connect(db_path)
    try:
        project_identity = resolve_project(conn, project)
        assert project_identity is not None
        if project_sequence is None:
            project_sequence = allocate_project_sequence(conn, project_identity.id)
        conn.execute(
            """
            INSERT INTO items (
                id, title, type, status, priority, flow,
                rework_count, frozen, blocked, blocked_reason,
                github_issue, deployed_to, worktree,
                created_at, updated_at, source,
                project_id, project_sequence, deployment_flow
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item_id, title, item_type, status, priority, flow,
                rework_count, frozen, blocked, blocked_reason,
                github_issue, deployed_to, worktree,
                created_at, updated_at, source,
                project_identity.id, project_sequence, deployment_flow,
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
    fields (rework_count, frozen, id). Body and structured-field writes are
    rejected; use :func:`update_structured_field` for the latter.

    Raises ``ValueError`` for body writes and invalid fields.
    Raises ``sqlite3.Error`` on DB failure.
    """
    if field == "body":
        raise ValueError(
            "Raw body writes are no longer supported. "
            "items.body is a rendered projection. Write to a structured field instead: "
            "spec, design_spec, technical_plan, worktree_plan, "
            "shepherd_log, shepherd_caveats, test_results, deploy_log"
        )

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
        conn.execute(
            f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
            (value, now, item_id),
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
                (content, now, now, source, item_id),
            )
        elif field in CONTENT_FIELDS:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s, "
                f"spec_updated_at = %s WHERE id = %s",
                (content, now, now, item_id),
            )
        else:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
                (content, now, item_id),
            )
        conn.commit()
    except ValueError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_item_multi(
    item_id: int,
    pairs: Dict[str, str],
    db_path: Optional[str] = None,
) -> None:
    """Batch-update multiple fields in a single transaction.

    *pairs* is a dict of ``{field: value}`` to set. Automatically sets
    ``updated_at``. Handles frozen boolean mapping, null mapping, and
    integer fields.

    Raises ``ValueError`` for body writes or empty pairs.
    Raises ``sqlite3.Error`` on DB failure.
    """
    if not pairs:
        raise ValueError("No field=value pairs provided")
    if "body" in pairs:
        raise ValueError(
            "Raw body writes are no longer supported. "
            "items.body is a rendered projection."
        )

    now = _now_utc()
    set_clauses: List[str] = []
    params: List[Any] = []

    for field, value in pairs.items():
        set_clauses.append(f"{field} = %s")
        if field == "frozen":
            params.append(_map_frozen_write(value))
        elif field == "blocked":
            params.append(_map_blocked_write(value))
        elif value == "null":
            params.append(None)
        elif field in INTEGER_FIELDS:
            try:
                params.append(int(value))
            except (ValueError, TypeError):
                params.append(None)
        else:
            params.append(value)

    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(item_id)  # WHERE binding

    sql = f"UPDATE items SET {', '.join(set_clauses)} WHERE id = %s"

    conn = connect(db_path)
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(sql, tuple(params))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
