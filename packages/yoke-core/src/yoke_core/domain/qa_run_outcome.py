"""Recorded QA outcomes shared by item and activity readers."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_constants import RUN_COLUMNS


def qa_run_read_projection(row: Any) -> dict[str, Any]:
    """Project the judged outcome while preserving this attempt's evidence."""
    result = {column: _row_value(row, column) for column in RUN_COLUMNS}
    result["case_outcome"] = qa_run_outcome(row)
    return result


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def qa_run_outcome(row: Any) -> str:
    """Return the canonical QA outcome without changing activity vocabulary."""
    if _row_value(row, "retracted_at"):
        return "cancelled"
    if _row_value(row, "qa_kind") == "post_deploy_no_obligation":
        return "no_obligation"
    if _row_value(row, "waived_at"):
        return "waived"
    case_outcome = str(_row_value(row, "case_outcome") or "").strip().replace(" ", "_")
    if case_outcome and case_outcome != "needs_review":
        return case_outcome
    verdict = str(_row_value(row, "verdict") or "").strip().lower()
    if verdict == "pass":
        return "passed"
    if verdict in {"fail", "error"}:
        return "failed"
    if verdict in {"undetermined", "needs review", "needs_review"}:
        return "needs_review"
    # Capture status is retained evidence; a judgment of that same attempt
    # answers readiness without rewriting its original capture payload.
    if case_outcome:
        return case_outcome
    execution_status = str(_row_value(row, "execution_status") or "").strip().lower()
    if execution_status in {
        "queued",
        "running",
        "waiting",
        "captured",
        "capture_failed",
        "completed",
    }:
        return execution_status
    return "queued"
