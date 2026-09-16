"""Which Browser proofs a control plane can read without a project checkout.

A control plane serving a customer project holds no checkout of it, and the
QA gates used to refuse every Browser case on that ground alone — so a
release whose evidence was durable, authorized, and revision-stamped could
not be closed out at all. Two things genuinely need the checkout, and only
those two: evidence recorded at a path relative to it, and a capture that
stamped no exact revision, whose staleness could only be judged against the
branch. This module names the requirements in either state so the gate
refuses about them by requirement, with the reason and its repair.

Requirements with no qualifying capture at all are deliberately absent:
that is missing evidence, which the blocking scan and
``check_browser_evidence_present`` already refuse in their own words.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_artifact_handle import (
    ArtifactHandleError,
    BACKEND_LOCAL,
    parse_handle,
)
from yoke_core.domain.qa_browser_evidence_check import (
    _phase_and,
    _qualifying_capture,
)
from yoke_core.domain.qa_constants import (
    INVALID_BROWSER_METHOD_LABEL,
    browser_requirement_predicate,
)
from yoke_core.domain.served_revision_probe import is_full_revision


def _latest_qualifying_captures(
    conn, *, where: str, params: tuple, qa_phase: Optional[str]
) -> list[dict]:
    """The newest qualifying capture of each blocking Browser requirement."""
    phase_and = _phase_and(qa_phase)
    qualifying = _qualifying_capture("r", "qr")
    rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.method_id, qr.id AS run_id, qr.raw_result
        FROM qa_requirements r
        JOIN qa_runs qr ON qr.qa_requirement_id = r.id
        WHERE {where}{phase_and}
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND {browser_requirement_predicate("r")}
          AND {qualifying}
        ORDER BY r.id, qr.created_at DESC, qr.id DESC
        """,
        params,
    )
    latest: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        requirement_id = int(row["id"])
        if requirement_id in seen:
            continue
        seen.add(requirement_id)
        latest.append(row)
    return latest


def _checkout_bound_reason(conn, row) -> str:
    """Why this capture cannot be read without a checkout, or ``""``."""
    from yoke_core.domain.qa_gate_helpers import _extract_code_identity

    _, sha = _extract_code_identity(row["raw_result"])
    if not is_full_revision(sha or ""):
        return (
            "its latest capture records no exact revision, so only a checkout "
            "of the project could judge what that evidence was captured against"
        )
    handles = query_rows(
        conn,
        """
        SELECT artifact_handle FROM qa_artifacts
        WHERE qa_run_id = %s AND artifact_handle IS NOT NULL
          AND artifact_handle <> ''
        """,
        (int(row["run_id"]),),
    )
    for handle_row in handles:
        raw = handle_row["artifact_handle"]
        try:
            handle = parse_handle(raw)
        except ArtifactHandleError:
            # A malformed handle names no evidence at all, and
            # check_browser_artifact_disk refuses it with the reason that
            # matters; a checkout would not make it readable either.
            continue
        path = str(handle.get("path") or "")
        if handle["backend"] == BACKEND_LOCAL and not Path(path).is_absolute():
            return (
                f"its evidence is recorded at the checkout-relative path "
                f"{path!r}, which only a checkout of the project can resolve"
            )
    return ""


def checkout_bound_proof_findings(
    conn, *, where: str, params: tuple, qa_phase: Optional[str]
) -> list[tuple[int, str, str]]:
    """Blocking Browser requirements whose proof needs a project checkout.

    Each finding is ``(requirement_id, method_id, reason)``.
    """
    findings: list[tuple[int, str, str]] = []
    for row in _latest_qualifying_captures(
        conn, where=where, params=params, qa_phase=qa_phase
    ):
        reason = _checkout_bound_reason(conn, row)
        if reason:
            findings.append(
                (
                    int(row["id"]),
                    str(row["method_id"] or INVALID_BROWSER_METHOD_LABEL),
                    reason,
                )
            )
    return findings


__all__ = [
    "checkout_bound_proof_findings",
]
