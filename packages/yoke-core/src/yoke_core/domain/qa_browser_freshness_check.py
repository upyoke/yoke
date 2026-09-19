"""Whether a passing browser run covers the revision under verification.

Split from :mod:`qa_gate_helpers`, which resolves *which* revision that is.
The two answer different questions and grow independently: resolution gained
a control-plane fallback for hosts with no checkout, while the comparison
below is the same judgment either way.

A capture is covered when it was taken AT an accepted head, after the
latest commit, or against a build that already CARRIES an accepted head.
That third reading is what a checkout-less host has: it can resolve no
commit timestamp, so without it the comparison degrades to SHA equality,
and evidence from a deployment newer than the landing -- the only evidence
an item that changed no source can ever produce -- is called stale.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED,
    candidate_contains_commit,
)
from yoke_core.domain.qa_constants import INVALID_BROWSER_METHOD_LABEL
from yoke_core.domain.qa_gate_definitions import LatestCodeRef

#: One Browser requirement whose latest pass does not cover the latest code:
#: requirement id, method id, when that run happened, the revision it
#: recorded, and any reason its build could not be placed.
StaleBrowserRow = Tuple[int, str, Optional[str], Optional[str], str]

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


def _item_project_id(conn: Any, item_id: Optional[int]) -> Optional[int]:
    """Resolve the project whose repository answers commit questions."""
    if item_id is None:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    value = row["project_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value else None


def _build_carries_accepted(
    conn: Any,
    *,
    project_id: int,
    build_sha: str,
    heads: Tuple[str, ...],
) -> Tuple[bool, str]:
    """Whether the build a capture ran against already carries an accepted head.

    The comparison is the merge boundary's own containment reader, so
    "carries" means one thing across delivery, posture, and QA, and it
    answers on a host with no checkout of the project: that reader asks
    every source the host can offer, the repository provider included.

    An unanswerable comparison returns its reason rather than a definite
    no -- a host that could not look has not learned the build excludes the
    landing.
    """
    unknown = ""
    for head in heads:
        verdict = candidate_contains_commit(
            conn,
            int(project_id),
            candidate_lineage=build_sha,
            commit_sha=head,
        )
        if verdict.contained:
            return True, ""
        if verdict.state == UNDETERMINED and not unknown:
            # Keep asking: another accepted head may answer definitely, and
            # a definite yes beats an unreadable maybe.
            unknown = (
                f"whether the build it was captured against carries "
                f"{head[:12]} could not be determined ({verdict.reason}). "
                f"{verdict.recovery}"
            )
    return False, unknown


def _accepted_heads(latest_code: LatestCodeRef) -> Tuple[str, ...]:
    """Every revision this run may legitimately have been captured at."""
    return tuple(
        dict.fromkeys(
            sha for sha in (latest_code.sha, *latest_code.accepted_shas) if sha
        )
    )


def _run_covers_latest_code(
    run_row,
    latest_code: LatestCodeRef,
    *,
    conn: Optional[Any] = None,
    project_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """Whether one passing browser run covers the code under verification.

    The three readings are asked in cost order, and each is an acceptance on
    its own. Containment goes last because it reads the project's
    repository; it is also the only one a checkout-less host can answer,
    which is why it is asked rather than skipped there.

    Returns the verdict plus, when containment could not be resolved, the
    reason to carry into the refusal -- a build nothing could place is not a
    build shown to exclude the landing.
    """
    _, run_sha = _extract_code_identity(run_row["raw_result"])
    heads = _accepted_heads(latest_code)
    if run_sha and run_sha in set(heads):
        return True, ""
    created_at = run_row["created_at"] or ""
    if latest_code.timestamp and created_at >= latest_code.timestamp:
        return True, ""
    if not run_sha or conn is None or project_id is None:
        return False, ""
    return _build_carries_accepted(
        conn, project_id=project_id, build_sha=run_sha, heads=heads
    )


def _browser_run_is_fresh(
    run_row,
    latest_code: LatestCodeRef,
    *,
    conn: Optional[Any] = None,
    project_id: Optional[int] = None,
) -> bool:
    """Return True when a passing browser run covers the latest code."""
    return _run_covers_latest_code(
        run_row, latest_code, conn=conn, project_id=project_id
    )[0]


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
    item_id: Optional[int] = None,
) -> List[StaleBrowserRow]:
    """Return Browser method cases whose latest pass misses latest code.

    ``item_id`` names the item whose project repository answers the
    containment reading; without it that reading is unavailable and the
    comparison stays membership and timestamp only.
    """
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
    project_id = _item_project_id(conn, item_id) if req_rows else None
    stale: List[StaleBrowserRow] = []
    for row in req_rows:
        latest_run = _latest_browser_run(conn, int(row["id"]))
        if latest_run is None:
            continue
        covered, note = _run_covers_latest_code(
            latest_run, latest_code, conn=conn, project_id=project_id
        )
        if covered:
            continue
        _, run_sha = _extract_code_identity(latest_run["raw_result"])
        stale.append(
            (
                int(row["id"]),
                str(row["method_id"] or INVALID_BROWSER_METHOD_LABEL),
                str(latest_run["created_at"] or "") or None,
                run_sha,
                note,
            )
        )
    return stale


def _browser_freshness_errors(
    *,
    name: str,
    transition_name: str,
    latest_code: LatestCodeRef,
    stale_rows: List[StaleBrowserRow],
    bypass_hint: Optional[str] = None,
) -> List[str]:
    """Build a user-facing stale browser evidence error block."""
    errors = [
        f"Error: Cannot transition {name} to '{transition_name}' -- {len(stale_rows)} browser requirement(s) have only stale passing runs.",
        "  Browser runs must be captured at, after, or against a build that "
        "carries the latest code on the branch.",
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
    for req_id, method_id, latest_run_at, run_sha, note in stale_rows:
        detail = (
            f"  - Requirement #{req_id} ({method_id}): latest passing run at "
            f"{latest_run_at or '<unknown>'}"
        )
        if run_sha:
            detail += f", run SHA {run_sha}"
        if note:
            # Re-running the case would record the same revision again, so a
            # build that could not be placed says so instead.
            detail += f" -- {note}"
        errors.append(detail)
    return errors


__all__ = [
    "StaleBrowserRow",
    "_browser_freshness_errors",
    "_extract_code_identity",
    "_browser_run_is_fresh",
    "_collect_stale_browser_requirements",
    "_latest_browser_run",
    "_run_covers_latest_code",
]
