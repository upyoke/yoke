"""Whether a passing browser run covers the revision under verification.

Split from :mod:`qa_gate_helpers`, which resolves *which* revision that is.
The two answer different questions and grow independently: resolution gained
a control-plane fallback for hosts with no checkout, while the comparison
below is the same judgment either way.
"""

from __future__ import annotations

import json
from typing import List, Optional, Tuple

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_constants import INVALID_BROWSER_METHOD_LABEL
from yoke_core.domain.qa_gate_definitions import LatestCodeRef

def _extract_code_identity(raw_result: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract browser QA code identity from raw_result JSON when present."""
    if not raw_result:
        return None, None
    try:
        payload = json.loads(raw_result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    code_identity = payload.get("code_identity")
    if not isinstance(code_identity, dict):
        return None, None
    branch = code_identity.get("branch")
    sha = code_identity.get("sha")
    return (
        str(branch) if branch else None,
        str(sha) if sha else None,
    )


def _browser_run_is_fresh(run_row, latest_code: LatestCodeRef) -> bool:
    """Return True when a passing browser run matches the latest code."""
    _, run_sha = _extract_code_identity(run_row["raw_result"])
    if run_sha and run_sha in {
        sha for sha in (latest_code.sha, *latest_code.accepted_shas) if sha
    }:
        return True
    created_at = run_row["created_at"] or ""
    if latest_code.timestamp and created_at >= latest_code.timestamp:
        return True
    return False


def _latest_browser_run(conn, requirement_id: int):
    """Return the latest passing browser-substrate run for a requirement."""
    return query_one(
        conn,
        """
        SELECT id, created_at, raw_result
        FROM qa_runs
        WHERE qa_requirement_id = %s
          AND verdict = 'pass'
          AND performed_by <> 'agent'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (requirement_id,),
    )


def _collect_stale_browser_requirements(
    conn,
    *,
    where: str,
    params: tuple,
    latest_code: LatestCodeRef,
    qa_phase: Optional[str] = "verification",
) -> List[Tuple[int, str, Optional[str], Optional[str]]]:
    """Return Browser method cases whose latest pass misses latest code."""
    from yoke_core.domain.qa_constants import browser_requirement_predicate

    phase_sql = ""
    phase_params: tuple = ()
    if qa_phase is not None:
        phase_sql = "AND r.qa_phase = %s"
        phase_params = (qa_phase,)
    req_rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.method_id
        FROM qa_requirements r
        WHERE {where}
          {phase_sql}
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND {browser_requirement_predicate("r")}
          AND EXISTS (
            SELECT 1 FROM qa_runs qr
            WHERE qr.qa_requirement_id = r.id
              AND qr.verdict = 'pass'
              AND qr.performed_by <> 'agent'
          )
        """,
        (*params, *phase_params),
    )
    stale: List[Tuple[int, str, Optional[str], Optional[str]]] = []
    for row in req_rows:
        latest_run = _latest_browser_run(conn, int(row["id"]))
        if latest_run is None:
            continue
        if _browser_run_is_fresh(latest_run, latest_code):
            continue
        _, run_sha = _extract_code_identity(latest_run["raw_result"])
        stale.append(
            (
                int(row["id"]),
                str(row["method_id"] or INVALID_BROWSER_METHOD_LABEL),
                str(latest_run["created_at"] or "") or None,
                run_sha,
            )
        )
    return stale


def _browser_freshness_errors(
    *,
    name: str,
    transition_name: str,
    latest_code: LatestCodeRef,
    stale_rows: List[Tuple[int, str, Optional[str], Optional[str]]],
    bypass_hint: Optional[str] = None,
) -> List[str]:
    """Build a user-facing stale browser evidence error block."""
    errors = [
        f"Error: Cannot transition {name} to '{transition_name}' -- {len(stale_rows)} browser requirement(s) have only stale passing runs.",
        "  Browser runs must match the latest code on the branch.",
    ]
    if latest_code.branch:
        errors.append(f"  Branch: {latest_code.branch}")
    if latest_code.sha:
        errors.append(f"  Latest SHA: {latest_code.sha}")
    if latest_code.timestamp:
        errors.append(f"  Latest commit: {latest_code.timestamp}")
    errors.append(
        "  Re-run each materialized Browser case with `yoke qa case run "
        "--requirement-id <REQ_ID>` to generate fresh passing runs."
    )
    if bypass_hint:
        errors.append(bypass_hint)
    for req_id, method_id, latest_run_at, run_sha in stale_rows:
        detail = (
            f"  - Requirement #{req_id} ({method_id}): latest passing run at "
            f"{latest_run_at or '<unknown>'}"
        )
        if run_sha:
            detail += f", run SHA {run_sha}"
        errors.append(detail)
    return errors


__all__ = [
    "_browser_freshness_errors",
    "_extract_code_identity",
    "_browser_run_is_fresh",
    "_collect_stale_browser_requirements",
    "_latest_browser_run",
]
