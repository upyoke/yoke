"""Per-item read command handlers.

Owns the SELECT-one commands: ``item-get`` (single field with virtual-body
support and large-text streaming), ``item-row`` (full canonical row),
``item-progress`` (progress view), and ``item-render`` (rendered body from
structured fields).
"""

from __future__ import annotations

import os
import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
)
from yoke_core.api.service_client_items_parsing import (
    _QI_ALL_FIELDS,
    _QI_LARGE_TEXT_FIELDS,
    _QI_VIRTUAL_FIELDS,
    _parse_item_id,
    _resolve_item_ref,
)
from yoke_core.domain.project_identity import item_project_join_select


def _view_exists(conn, view_name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS view_count FROM information_schema.views "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (view_name,),
    ).fetchone()
    return bool(row and row["view_count"] > 0)


def cmd_item_get(args: list[str]) -> int:
    """Get a single field value for an item.

    Usage: item-get <item-id> <field>

    Output: field value (large text fields streamed via temp file to avoid truncation).
    Exit 0 on success (including empty fields on existing items),
    1 on item not found, 2 on usage error.

    Uses a temp file for large text fields so callers receive complete output.
    """
    if len(args) < 2:
        print("Usage: item-get <item-id> <field>", file=sys.stderr)
        return 2

    if _parse_item_id(args[0]) is None:
        print(f"Error: invalid item ID '{args[0]}'", file=sys.stderr)
        return 2

    field = args[1]
    if field not in _QI_ALL_FIELDS:
        print(f"Error: unknown field '{field}'. Valid: {','.join(sorted(_QI_ALL_FIELDS))}", file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        item_id = _resolve_item_ref(conn, args[0])
        if item_id is None:
            return 1
        # Resolution confirms existence for refs; verify the bare-id path too.
        exists_row = conn.execute(
            "SELECT COUNT(*) AS item_count FROM items WHERE id = %s", (item_id,)
        ).fetchone()
        exists = exists_row["item_count"] if exists_row else 0
        if not exists:
            return 1

        # Virtual field: "body" is rendered on demand
        if field in _QI_VIRTUAL_FIELDS:
            from yoke_core.domain.render_body import build_body
            value = build_body(conn, int(item_id)) or ""
        elif field == "project":
            row = conn.execute(
                "SELECT COALESCE(CAST(p.slug AS TEXT), '') AS value "
                "FROM items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.id = %s",
                (item_id,),
            ).fetchone()
            value = row["value"] if row else ""
        else:
            # Fetch the field value from DB
            row = conn.execute(
                f"SELECT COALESCE(CAST({field} AS TEXT), '') AS value FROM items WHERE id = %s",
                (item_id,),
            ).fetchone()
            value = row["value"] if row else ""

        if field in _QI_LARGE_TEXT_FIELDS:
            if not value:
                print(
                    f"query-items: YOK-{item_id} field '{field}' is null/empty",
                    file=sys.stderr,
                )
                return 0

            # Has content -- stream via temp file to avoid truncation
            import tempfile as _tf
            with _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                tmp.write(value)
                tmp_path = tmp.name
            try:
                with open(tmp_path, "r") as f:
                    sys.stdout.write(f.read())
            finally:
                os.unlink(tmp_path)
            return 0

        # Non-large-text field
        if not value:
            print(
                f"query-items: YOK-{item_id} field '{field}' is null/empty",
                file=sys.stderr,
            )
            return 0
        print(value)
        return 0
    finally:
        conn.close()


def cmd_item_row(args: list[str]) -> int:
    """Get a full pipe-delimited row for an item.

    Usage: item-row <item-id>

    Output: pipe-delimited full row in canonical column order matching
    the canonical row order expected by item-row callers:
    id|title|type|status|priority|flow|rework_count|frozen|
    github_issue|deployed_to|worktree|body|merged_at|created_at|updated_at|
    source|project|deployment_flow|deploy_stage
    Exit 0 on found, 1 on not found.
    """
    if len(args) < 1:
        print("Usage: item-row <item-id>", file=sys.stderr)
        return 2

    if _parse_item_id(args[0]) is None:
        print(f"Error: invalid item ID '{args[0]}'", file=sys.stderr)
        return 2

    # Canonical field order -- "body" is virtual
    _ROW_DB_FIELDS = [
        "id", "title", "type", "status", "priority", "flow",
        "rework_count", "frozen", "github_issue",
        "deployed_to", "worktree", "merged_at",
        "created_at", "updated_at", "source", "project",
        "deployment_flow", "deploy_stage",
    ]
    _BODY_INSERT_INDEX = 11  # body goes after worktree in output
    select_cols, needs_project = item_project_join_select(_ROW_DB_FIELDS)
    join = " JOIN projects p ON p.id = i.project_id" if needs_project else ""
    sql = f"SELECT {select_cols} FROM items i{join} WHERE i.id = %s"

    conn = _get_db_readonly()
    try:
        item_id = _resolve_item_ref(conn, args[0])
        if item_id is None:
            return 1
        row = conn.execute(sql, (item_id,)).fetchone()
        if row is None:
            return 1
        # Render body on demand
        from yoke_core.domain.render_body import build_body
        rendered_body = build_body(conn, int(item_id)) or ""
        values = list(str(v) for v in row)
        # Insert rendered body at the expected position
        values.insert(_BODY_INSERT_INDEX, rendered_body.replace("\n", "\\n"))
        print("|".join(values))
        return 0
    finally:
        conn.close()


def cmd_item_progress(args: list[str]) -> int:
    """Get progress view for an item.

    Usage: item-progress <item-id>

    Output: pipe-delimited progress view row:
        status|flow_name|run_id|current_stage|target_env|stage_progress|done_description|qa_summary|pipeline_blocked_reason
    Exit 0 on found, 1 on not found, 0 with empty on missing view.

    Rename: the view column ``blocked_reason`` was renamed to
    ``pipeline_blocked_reason`` so the deployment-run blocker name no longer
    collides with the new ``items.blocked_reason`` column on a JOIN.
    """
    if len(args) < 1:
        print("Usage: item-progress <item-id>", file=sys.stderr)
        return 2

    if _parse_item_id(args[0]) is None:
        print(f"Error: invalid item ID '{args[0]}'", file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        item_id = _resolve_item_ref(conn, args[0])
        if item_id is None:
            return 1
        if not _view_exists(conn, "item_progress_view"):
            # View doesn't exist -- exit 0 with empty output
            return 0

        progress_fields = [
            "status", "flow_name", "run_id", "current_stage", "target_env",
            "stage_progress", "done_description", "qa_summary",
            "pipeline_blocked_reason",
        ]
        select_cols = ", ".join(f"COALESCE({f}, '')" for f in progress_fields)
        row = conn.execute(
            f"SELECT {select_cols} FROM item_progress_view WHERE item_id = %s",
            (item_id,),
        ).fetchone()

        if row is None:
            return 1
        print("|".join(str(v) for v in row))
        return 0
    finally:
        conn.close()


def cmd_item_render(args: list[str]) -> int:
    """Render item body from structured fields.

    Usage: item-render <item-id>

    Output: rendered body assembled from structured fields, item_sections,
    and shepherd-log data. Exit 0 on success, 1 on not found, 2 on usage error.
    """
    if len(args) < 1:
        print("Usage: item-render <item-id>", file=sys.stderr)
        return 2

    if _parse_item_id(args[0]) is None:
        print(f"Error: invalid item ID '{args[0]}'", file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        item_id = _resolve_item_ref(conn, args[0])
    finally:
        conn.close()
    if item_id is None:
        return 1

    from yoke_core.domain.render_body import render_item
    return render_item(int(item_id))


__all__ = [
    "cmd_item_get",
    "cmd_item_row",
    "cmd_item_progress",
    "cmd_item_render",
]
