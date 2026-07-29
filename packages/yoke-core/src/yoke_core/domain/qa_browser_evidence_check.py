"""Browser-evidence sub-checks shared by verification and done gates.

Each helper returns ``None`` when the check passes; otherwise it returns a
``GateResult`` with the canonical browser-gate error messages.
``qa_phase="verification"`` scopes SQL to verification-phase rows and runs
the empty-handle pre-check; ``qa_phase=None`` omits both. The
``bypass_hint`` parameter on ``check_browser_artifact_disk`` is appended to
the missing-files error (done-gate uses it; verification-gate passes None).

Evidence presence is handle-typed: ``local`` handles must exist on this
machine's disk; well-formed ``s3`` handles are present by construction
(the upload completed before the row was recorded) and gates deliberately
add no network round-trips. Malformed handles fail the gate loudly.
"""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.qa_artifact_handle import (
    ArtifactHandleError,
    handle_address,
    is_present,
    parse_handle,
)
from yoke_core.domain.qa_gate_definitions import GateResult
from yoke_core.domain.qa_constants import browser_requirement_predicate


_REMEDIATION_LINES = (
    "",
    "  Remediation:",
    "  Re-run each named materialized case through the shared executor:",
    "       yoke qa case run --requirement-id <REQ_ID> --base-url <URL> \\",
    "         --expected-branch <BRANCH> --expected-sha <SHA>",
    "  For substrate diagnosis only, capture the URL without recording a",
    "  parallel QA verdict:",
    "       yoke qa browser screenshot <URL> --output <path.png>",
)


def _phase_and(qa_phase: Optional[str]) -> str:
    """Return ``AND r.qa_phase = 'verification'`` (with leading newline) or ''."""
    if qa_phase == "verification":
        return "\n          AND r.qa_phase = 'verification'"
    return ""


def _qualifying_capture(requirement: str, capture: str) -> str:
    agent_case = (
        f"COALESCE({requirement}.verdict_path = 'agent' "
        f"OR {requirement}.method_id = 'browser-inspection', FALSE)"
    )
    linked_agent_pass = f"""
        EXISTS (
          SELECT 1 FROM qa_plan_review_verdicts prv
          JOIN qa_plan_review_bundles prb ON prb.id = prv.bundle_id
          JOIN qa_runs review_run ON review_run.id = prv.review_run_id
          WHERE prv.requirement_id = {requirement}.id
            AND prv.capture_run_id = {capture}.id
            AND prv.verdict = 'pass'
            AND prb.state = 'completed'
            AND review_run.executor_type = 'agent'
            AND review_run.verdict = 'pass'
        )
    """
    return f"""
        {capture}.executor_type = 'browser_substrate'
        AND (
          (NOT {agent_case} AND {capture}.verdict = 'pass')
          OR (
            {agent_case}
            AND {capture}.execution_status = 'captured'
            AND {capture}.case_outcome = 'needs_review'
            AND {linked_agent_pass}
          )
        )
    """


def _browser_proof_exists(requirement: str) -> str:
    return f"""
        EXISTS (
          SELECT 1 FROM qa_runs proof_capture
          JOIN qa_artifacts proof_artifact
            ON proof_artifact.qa_run_id = proof_capture.id
          WHERE proof_capture.qa_requirement_id = {requirement}.id
            AND {_qualifying_capture(requirement, 'proof_capture')}
        )
    """


def check_browser_evidence_present(
    conn,
    *,
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
) -> Optional[GateResult]:
    """Verify each blocking Browser method case has substrate evidence."""
    browser_where = browser_requirement_predicate("r")
    proof_exists = _browser_proof_exists("r")
    browser_no_evidence = query_scalar(
        conn,
        f"""
        SELECT COUNT(*) FROM qa_requirements r
        WHERE {where}
          AND r.qa_phase = 'verification'
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND {browser_where}
          AND NOT {proof_exists}
        """,
        params,
    )
    if not browser_no_evidence or browser_no_evidence <= 0:
        return None

    errors = [
        f"Error: Cannot transition {name} to '{transition_name}' -- {browser_no_evidence} Browser method case(s) lack substrate evidence.",
        "  Browser check requires a passing browser_substrate run with an artifact.",
        "  Browser inspection requires a captured browser_substrate artifact linked",
        "  to its completed passing agent-review verdict.",
        f"  Remediation: run `/yoke advance {name} {transition_name}` which executes browser QA automatically before updating status.",
    ]
    rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.method_id FROM qa_requirements r
        WHERE {where}
          AND r.qa_phase = 'verification'
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND {browser_where}
          AND NOT {proof_exists}
        """,
        params,
    )
    for row in rows:
        errors.append(
            f"  - Requirement #{row['id']} ({row['method_id'] or 'legacy Browser case'}): no linked substrate-and-verdict proof"
        )
    errors.extend(_REMEDIATION_LINES)
    return GateResult(passed=False, errors=errors)


def check_browser_artifact_disk(
    conn,
    *,
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
    repo_root: str,
    qa_phase: Optional[str] = None,
    bypass_hint: Optional[str] = None,
) -> Optional[GateResult]:
    """Verify recorded browser artifact handles name evidence that exists."""
    phase_and = _phase_and(qa_phase)
    browser_where = browser_requirement_predicate("r")

    if qa_phase == "verification":
        # Empty/null-handle pre-check is verification-only.
        qualifying = _qualifying_capture("r", "qr")
        qualifying_with_handle = _qualifying_capture("r", "qr2")
        fake_rows = query_rows(
            conn,
            f"""
            SELECT DISTINCT r.id, r.method_id FROM qa_requirements r
            WHERE {where}{phase_and}
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL
              AND {browser_where}
              AND EXISTS (
                SELECT 1 FROM qa_runs qr
                JOIN qa_artifacts qa ON qa.qa_run_id = qr.id
                WHERE qr.qa_requirement_id = r.id
                  AND {qualifying}
              )
              AND NOT EXISTS (
                SELECT 1 FROM qa_runs qr2
                JOIN qa_artifacts qa2 ON qa2.qa_run_id = qr2.id
                WHERE qr2.qa_requirement_id = r.id
                  AND {qualifying_with_handle}
                  AND qa2.artifact_handle IS NOT NULL
                  AND qa2.artifact_handle <> ''
              )
            """,
            params,
        )
        if fake_rows:
            errors = [
                f"Error: Cannot transition {name} to '{transition_name}' -- browser artifact(s) have no artifact handle recorded.",
            ]
            for row in fake_rows:
                errors.append(
                    f"  - Requirement #{row['id']} ({row['method_id'] or 'legacy Browser case'}): artifact has no artifact_handle"
                )
            return GateResult(passed=False, errors=errors)

    # Check the recorded handles: local handles must exist on disk;
    # s3 handles are durable evidence and pass structurally.
    qualifying = _qualifying_capture("r", "qr")
    art_rows = query_rows(
        conn,
        f"""
        SELECT DISTINCT qa.artifact_handle FROM qa_artifacts qa
        JOIN qa_runs qr ON qa.qa_run_id = qr.id
        JOIN qa_requirements r ON qr.qa_requirement_id = r.id
        WHERE r.blocking_mode = 'blocking'{phase_and}
          AND r.waived_at IS NULL
          AND {browser_where}
          AND {qualifying}
          AND qa.artifact_handle IS NOT NULL
          AND qa.artifact_handle <> ''
          AND {where}
        """,
        params,
    )
    missing_count = 0
    for row in art_rows:
        raw = row["artifact_handle"]
        if not raw:
            continue
        try:
            handle = parse_handle(raw)
        except ArtifactHandleError as exc:
            print(
                f"  - malformed artifact handle ({exc}): {raw}",
                file=sys.stderr,
            )
            missing_count += 1
            continue
        if not is_present(handle, repo_root=repo_root):
            print(
                "  - artifact file not found at "
                f"{handle_address(handle, repo_root=repo_root)} "
                f"(artifact_handle: {raw})",
                file=sys.stderr,
            )
            missing_count += 1

    if missing_count > 0:
        errors = [
            f"Error: Cannot transition {name} to '{transition_name}' -- {missing_count} browser artifact handle(s) name no real evidence.",
            "  Artifact handle rows exist in the DB but the evidence they name is missing or malformed.",
            "  This may indicate fabricated artifact records. Re-run browser scenarios to generate real artifacts.",
        ]
        if bypass_hint:
            errors.append(bypass_hint)
        return GateResult(passed=False, errors=errors)

    return None
