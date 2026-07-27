"""Truthful current-run proof summaries shared by QA read models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _payload(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if raw_result in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw_result))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def qa_run_outcome(row: Any) -> str:
    """Return the canonical QA outcome without changing activity vocabulary."""
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
    if verdict in {"inconclusive", "needs review", "needs_review"}:
        return "needs_review"
    execution_status = str(_row_value(row, "execution_status") or "").strip().lower()
    if execution_status in {"queued", "running", "waiting"}:
        return execution_status
    return "queued"


def qa_precondition_reason(raw_result: Any) -> str | None:
    """Extract the recorded error behind a precondition-blocked run."""
    payload = _payload(raw_result)
    evidence = payload.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    baseline = evidence.get("baseline_evidence")
    baseline = baseline if isinstance(baseline, dict) else {}
    reason = (
        payload.get("precondition_reason")
        or payload.get("error_code")
        or evidence.get("error_code")
        or baseline.get("error_code")
    )
    text = str(reason or "").strip()
    return text or None


def _current_proof_hint(raw_result: Any) -> str | None:
    payload = _payload(raw_result)
    evidence = payload.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    for candidate in (
        payload.get("proof_summary"),
        evidence.get("proof_summary"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    lease_summary = str(
        payload.get("lease_summary") or evidence.get("lease_summary") or ""
    ).strip()
    evidence_summary = str(
        payload.get("evidence_summary")
        or evidence.get("evidence_summary")
        or evidence.get("summary")
        or ""
    ).strip()
    combined = " · ".join(part for part in (lease_summary, evidence_summary) if part)
    if combined:
        return combined
    return None


def _matching_artifact_count(
    artifacts: Mapping[str, int],
    fragment: str,
) -> int:
    return sum(
        count
        for artifact_type, count in artifacts.items()
        if fragment in artifact_type.lower()
    )


def qa_proof_summary(
    *,
    method_id: str | None,
    run_id: int | None,
    raw_result: Any,
    artifacts: Mapping[str, int],
    outcome: str,
    capture_degraded_reason: str | None,
    host_baseline: str | None,
    precondition_reason: str | None,
) -> str:
    """Summarize evidence for the latest run, never the expected result."""
    if run_id is None:
        return "not run"

    supplied = _current_proof_hint(raw_result)
    if supplied:
        return supplied

    if outcome == "blocked_on_precondition":
        baseline = str(host_baseline or "precondition").replace("_", " ")
        reason = str(precondition_reason or "blocked").replace("_", " ")
        return f"baseline {baseline} {reason} — case did not run"

    payload = _payload(raw_result)
    evidence_count = sum(artifacts.values())
    screenshots = _matching_artifact_count(artifacts, "screenshot")
    traces = _matching_artifact_count(artifacts, "trace")
    if method_id == "command":
        exit_code = payload.get("exit_code")
        return (
            f"exit {exit_code} · output tail"
            if exit_code is not None
            else "command output"
        )
    if method_id == "browser-check":
        if traces:
            return "assertions · trace"
        if screenshots:
            return (
                f"assertions · {screenshots} "
                f"{'screenshot' if screenshots == 1 else 'screenshots'}"
            )
        return "assertion result"
    if method_id == "browser-inspection":
        recorded = int(payload.get("recorded_screenshots") or screenshots)
        if recorded:
            return f"{recorded} {'screenshot' if recorded == 1 else 'screenshots'}"
        return "no screenshot evidence"
    if method_id == "terminal-check":
        suffix = (
            f" · {screenshots} {'screenshot' if screenshots == 1 else 'screenshots'}"
            if screenshots
            else ""
        )
        return f"step transcript{suffix}"
    if method_id == "terminal-inspection":
        if capture_degraded_reason:
            return f"text capture + reason — {capture_degraded_reason}"
        if screenshots:
            return (
                f"paired text + {screenshots} Terminal "
                f"{'screenshot' if screenshots == 1 else 'screenshots'}"
            )
        return "text capture · no image evidence"
    if method_id == "machine-state-check":
        return "assertion commands · outputs"
    if evidence_count:
        return f"{evidence_count} {'artifact' if evidence_count == 1 else 'artifacts'}"
    return "no evidence recorded"


def qa_artifact_counts_by_run(
    conn: Any,
    run_ids: set[int],
) -> dict[int, dict[str, int]]:
    """Return artifact-type counts for a batch of QA runs."""
    if not run_ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in run_ids)
    rows = query_rows(
        conn,
        "SELECT qa_run_id, artifact_type, COUNT(*) AS artifact_count "
        "FROM qa_artifacts "
        f"WHERE qa_run_id IN ({placeholders}) "
        "GROUP BY qa_run_id, artifact_type",
        tuple(sorted(run_ids)),
    )
    result: dict[int, dict[str, int]] = {}
    for row in rows:
        result.setdefault(int(row["qa_run_id"]), {})[str(row["artifact_type"])] = int(
            row["artifact_count"]
        )
    return result


__all__ = [
    "qa_artifact_counts_by_run",
    "qa_precondition_reason",
    "qa_proof_summary",
    "qa_run_outcome",
]
