"""Auto-append the documented UNRESOLVED File Budget at idea status.

Refine-entry readiness treated a missing File Budget section as
unrecoverable even though the repair is mechanical boilerplate and
budget resolution belongs to refine. This helper writes the documented
marker through the structured spec write, then re-runs readiness.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.file_budget_paths import apply_unresolved_file_budget_marker
from yoke_core.domain.idea_readiness_repair import (
    CLASS_MIXED_STALE_COUNT,
    RepairOutcome,
)


MISSING_FILE_BUDGET_CODE = "MISSING_FILE_BUDGET"


class _NullSink:
    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def _read_item(item_id: int) -> Tuple[str, str]:
    from yoke_core.domain.backlog_queries import (
        _query_item_field, _resolve_write_db_path,
    )
    from yoke_core.domain.db_helpers import connect

    conn = connect(_resolve_write_db_path())
    try:
        spec = _query_item_field(conn, item_id, "spec") or ""
        placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT status FROM items WHERE id = {placeholder}", (item_id,),
        ).fetchone()
    finally:
        conn.close()
    status = ""
    if row is not None:
        raw = row["status"] if hasattr(row, "keys") else row[0]
        status = str(raw or "")
    return spec, status


def _rerun_readiness(item_id: int) -> Tuple[str, List[Dict[str, Any]]]:
    from yoke_core.domain.idea_readiness_check import run_all_checks
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path

    conn = _connect_raw(_resolve_db_path())
    try:
        issues = run_all_checks(conn, item_id)
    finally:
        conn.close()
    payload = [
        {"code": i.code, "message": i.message,
         "remediation": i.remediation, "context": i.context}
        for i in issues
    ]
    return ("pass" if not issues else "block", payload)


def _emit_audit(*, item_id: int, rerun_verdict: str) -> bool:
    try:
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "IdeaReadinessAutofixApplied",
            event_kind="lifecycle", event_type="readiness_repair",
            source_type="backend", severity="INFO", outcome="completed",
            item_id=str(item_id),
            context={
                "field": "spec",
                "action": "append_unresolved_file_budget",
                "rerun_verdict": rerun_verdict,
            },
        )
        return bool(getattr(result, "wrote", False) or getattr(result, "event_id", ""))
    except Exception:
        return False


def attempt_missing_file_budget_repair(*, item_id: int) -> RepairOutcome:
    """Append the documented UNRESOLVED marker when status is idea."""
    base = {"classification": CLASS_MIXED_STALE_COUNT, "item_id": item_id}
    spec_text, status = _read_item(item_id)
    if status != "idea":
        return RepairOutcome(
            success=False, **base,
            refused_paths=[{"reason": "not_idea_status", "status": status}],
            error="UNRESOLVED File Budget auto-append is idea-status only",
        )
    updated = apply_unresolved_file_budget_marker(spec_text)
    if updated == spec_text:
        return RepairOutcome(
            success=False, **base,
            error="repair would be a no-op; refusing redundant write",
        )
    write_result = execute_structured_write(
        item_id=item_id, field="spec", content=updated,
        source="readiness-autofix", out=_NullSink(),
    )
    if not write_result.get("success"):
        return RepairOutcome(success=False, **base, error=str(
            write_result.get("error") or "structured write failed"
        ))
    rerun_verdict, rerun_issues = _rerun_readiness(item_id)
    return RepairOutcome(
        success=(rerun_verdict == "pass"), **base,
        field_written="spec", rerun_verdict=rerun_verdict,
        rerun_issues=rerun_issues,
        audit_emitted=_emit_audit(item_id=item_id, rerun_verdict=rerun_verdict),
    )


def maybe_repair_missing_file_budget(
    *, item_id: int, issues: List[Dict[str, Any]],
) -> Tuple[Optional[RepairOutcome], List[Dict[str, Any]]]:
    """Append the marker when present; continue claim coverage if leftover."""
    remaining = [
        issue for issue in issues
        if str(issue.get("code") or "") != MISSING_FILE_BUDGET_CODE
    ]
    if len(remaining) == len(issues):
        return None, issues
    outcome = attempt_missing_file_budget_repair(item_id=item_id)
    if not outcome.success or not remaining:
        return outcome, remaining
    return None, remaining


__all__ = [
    "MISSING_FILE_BUDGET_CODE",
    "attempt_missing_file_budget_repair",
    "maybe_repair_missing_file_budget",
]
