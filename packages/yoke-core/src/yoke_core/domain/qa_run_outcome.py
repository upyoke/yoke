"""Recorded QA outcomes shared by item and activity readers."""

from collections.abc import Mapping
from typing import Any


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def qa_run_outcome(row: Any) -> str:
    """Return the canonical QA outcome without changing activity vocabulary."""
    if _row_value(row, "qa_kind") == "post_deploy_no_obligation":
        return "no_obligation"
    if _row_value(row, "waived_at"):
        return "waived"
    case_outcome = str(_row_value(row, "case_outcome") or "").strip()
    if case_outcome:
        return case_outcome.replace(" ", "_")
    verdict = str(_row_value(row, "verdict") or "").strip().lower()
    if verdict == "pass":
        return "passed"
    if verdict in {"fail", "error"}:
        return "failed"
    if verdict in {"undetermined", "needs review", "needs_review"}:
        return "needs_review"
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
