"""Backlog structured-field write operation — `execute_structured_write`
validates the structured-field payload (JSON-shape fields, freeze-immutability
locks, shrinkage guard, empty-overwrite guard), writes the field with
content-tracking timestamps where applicable, re-renders the body, and
syncs the body back to GitHub.
"""

from __future__ import annotations

import os
import sys
from time import perf_counter
from typing import Optional, TextIO

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    CONTENT_TRACKING_FIELDS,
    VALID_STRUCTURED_FIELDS,
    _assert_write_db_ready,
    _now_iso,
    _query_item_field,
    _resolve_write_db_path,
)
from yoke_core.domain import backlog_rendering as _rendering


def execute_structured_write(
    item_id: int,
    field: str,
    file_path: str = "",
    force: bool = False,
    source: str = "",
    rebuild_board: bool = True,
    out: TextIO = sys.stdout,
    content: Optional[str] = None,
) -> dict:
    """Structured field write: DB write → render body → md regen → sync.

    Content can be provided via ``content`` (stdin path) or ``file_path``.
    Exactly one must be provided for every call.

    Returns a result dict with 'success', 'error', etc.
    """
    if field not in VALID_STRUCTURED_FIELDS:
        return {
            "success": False,
            "error": f"invalid structured field: {field}",
        }

    # Mutual-exclusion: content vs file_path
    has_file = bool(file_path)
    has_content = content is not None
    if has_file and has_content:
        return {
            "success": False,
            "error": "cannot use both content and file_path; pick one",
        }
    if not has_file and not has_content:
        return {
            "success": False,
            "error": "structured field write requires file_path or content",
        }

    if has_file:
        if not os.path.isfile(file_path):
            return {
                "success": False,
                "error": f"file not found: {file_path}",
            }
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

    # JSON-shape structured field: reject malformed payload before DB write.
    if field == "browser_qa_metadata" and content and content.strip():
        from yoke_core.domain.browser_qa_metadata import (
            BrowserQaMetadataError,
            validate_json_string,
        )
        try:
            content = validate_json_string(content)
        except BrowserQaMetadataError as exc:
            return {
                "success": False,
                "error": f"browser_qa_metadata validation failed: {exc}",
            }
    if field == "db_mutation_profile" and content and content.strip():
        from yoke_core.domain.db_mutation_profile import (
            DbMutationProfileError,
            validate_json_string,
        )
        try:
            content = validate_json_string(content)
        except DbMutationProfileError as exc:
            return {
                "success": False,
                "error": f"db_mutation_profile validation failed: {exc}",
            }
    if field == "db_compatibility_attestation" and content and content.strip():
        from yoke_core.domain.db_compatibility_attestation import (
            DbCompatibilityAttestationError,
            validate_json_string,
        )
        try:
            content = validate_json_string(content)
        except DbCompatibilityAttestationError as exc:
            return {
                "success": False,
                "error": f"db_compatibility_attestation validation failed: {exc}",
            }

    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    try:
        existing = _query_item_field(conn, item_id, field) or ""
        # Safety net: refuse to overwrite non-empty with empty
        if not content or not content.strip():
            if existing and existing.strip():
                return {
                    "success": False,
                    "error": (
                        f"refusing to overwrite non-empty {field} with empty"
                        f" content for YOK-{item_id}"
                    ),
                }

        # Shrinkage guard
        if not force and content and content.strip():
            if existing:
                old_lines = existing.count("\n") + (
                    1 if existing and not existing.endswith("\n") else 0
                )
                new_lines = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
                if old_lines >= 10 and new_lines < (old_lines // 2):
                    return {
                        "success": False,
                        "error": (
                            f"refusing {field} write for YOK-{item_id}:"
                            f" new content ({new_lines} lines) is less than"
                            f" 50% of existing {field} ({old_lines} lines)."
                            " This may indicate content loss."
                            " Use --force to override."
                        ),
                    }

        if content == existing:
            return {
                "success": True,
                "changed": False,
                "body_sync_mode": "skipped_no_change",
                "body_budget_degraded": False,
                "body_sync_elapsed_ms": 0,
            }

        # Freeze-immutability enforcement for governed DB-mutation fields.
        # Locks profile.model_name once the sibling attestation has been
        # stamped with frozen_at; locks authored attestation fields under
        # the same condition.  The joint gate at idea -> refining-idea owns
        # stamping / clearing frozen_at; the write path only defends the
        # lock.
        if field == "db_mutation_profile" and content and content.strip():
            from yoke_core.domain.db_mutation_profile import check_model_name_frozen

            current_attestation = _query_item_field(conn, item_id, "db_compatibility_attestation")
            current_profile = _query_item_field(conn, item_id, "db_mutation_profile")
            freeze_err = check_model_name_frozen(
                current_attestation, current_profile, content
            )
            if freeze_err:
                return {"success": False, "error": freeze_err}

        if field == "db_compatibility_attestation" and content and content.strip():
            from yoke_core.domain.db_compatibility_attestation import (
                check_authored_fields_frozen,
            )

            current_attestation = _query_item_field(conn, item_id, "db_compatibility_attestation")
            freeze_err = check_authored_fields_frozen(current_attestation, content)
            if freeze_err:
                return {"success": False, "error": freeze_err}

        # Write field to DB
        now = _now_iso()
        if field in CONTENT_TRACKING_FIELDS and source:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s,"
                " spec_updated_at = %s, spec_updated_by = %s WHERE id = %s",
                (content, now, now, source, item_id),
            )
        elif field in CONTENT_TRACKING_FIELDS:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s,"
                " spec_updated_at = %s WHERE id = %s",
                (content, now, now, item_id),
            )
        else:
            conn.execute(
                f"UPDATE items SET {field} = %s, updated_at = %s WHERE id = %s",
                (content, now, item_id),
            )
        # Structured-field writes are real item activity for board-activity
        # semantics.
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=item_id)
        conn.commit()
    finally:
        conn.close()

    _src_label = file_path if file_path else "stdin"
    print(f"Updated: YOK-{item_id} {field} from {_src_label}", file=out)

    # Render body from structured fields
    if not _rendering._render_body(item_id, out):
        return {"success": False, "error": "body render failed"}

    # GitHub sync body.  ``_sync_body`` now returns ``(success, mode)``;
    # we destructure so the new ``body_sync_mode`` / ``body_budget_degraded``
    # keys flow into the return dict.
    sync_warning = ""
    sync_started = perf_counter()
    body_success, body_sync_mode = _rendering._sync_body(item_id, out)
    body_sync_elapsed_ms = int((perf_counter() - sync_started) * 1000)
    if not body_success:
        sync_warning = "sync_body failed"
        _rendering._record_sync_failure(item_id, "body", "sync_body failed")

    _rendering._maybe_rebuild_board(
        rebuild_board,
        respect_global_dry_run=False,
        out=out,
    )

    body_budget_degraded = body_sync_mode == "compact"

    result: dict = {
        "success": True,
        "changed": True,
        "body_sync_mode": body_sync_mode if body_success else None,
        "body_budget_degraded": body_budget_degraded if body_success else False,
        "body_sync_elapsed_ms": body_sync_elapsed_ms,
    }
    if sync_warning:
        result["sync_warning"] = sync_warning
    return result


__all__ = ["execute_structured_write"]
