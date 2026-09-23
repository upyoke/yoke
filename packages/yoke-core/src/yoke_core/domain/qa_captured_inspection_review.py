"""Link an agent review to a captured local-preview Browser inspection.

A browser-inspection capture can land from ``yoke qa case run --base-url``
against a workstation preview. The release gate still requires a completed
plan-review verdict row. Starting ``qa.plan_execution.begin`` to get that
bundle refuses when the project has no ``hosts.app``, and a local
``--target-env`` name owned by another project is refused. This module is
the review path that does not need a registered environment URL.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.qa_constants import (
    AGENT_VERDICT_PATH,
    BROWSER_INSPECTION_METHOD_ID,
    NEEDS_REVIEW_OUTCOME,
)
from yoke_core.domain.qa_plan_execution_store import marker


class CapturedInspectionReviewError(ValueError):
    """The requirement has no captured inspection ready for agent review."""


CAPTURED_INSPECTION_REVIEW_RECOVERY = (
    "A captured browser-inspection (case_outcome=needs_review) is reviewed "
    "with `yoke qa run record-verdict --requirement-id N --performed-by agent "
    "--verdict pass --verdict-reason TEXT`. Do not run qa.plan_execution.begin "
    "or bind --target-env for that review when the project has no hosts.app; "
    "a local target name owned by another project is refused. Capture first "
    "with `yoke qa case run --requirement-id N --base-url http://127.0.0.1:PORT`."
)

AGENT_IS_NOT_A_BROWSER_CAPTURE_RUNNER = (
    "performed_by 'agent' cannot capture a Browser case; use browser_substrate "
    "via `yoke qa case run --requirement-id N --base-url URL`. "
    + CAPTURED_INSPECTION_REVIEW_RECOVERY
)


def attach_agent_review_to_capture(
    conn: Any,
    *,
    requirement_id: int,
    review_run_id: int,
    verdict: str,
    rationale: str,
    actor_id: str,
    session_id: str,
) -> None:
    """Persist the gate's capture-to-review linkage for one inspection."""
    p = marker(conn)
    requirement = query_one(
        conn,
        "SELECT item_id, deployment_run_id, method_id, verdict_path, "
        f"workflow_transition_id FROM qa_requirements WHERE id={p}",
        (int(requirement_id),),
    )
    if requirement is None:
        raise CapturedInspectionReviewError(CAPTURED_INSPECTION_REVIEW_RECOVERY)
    if str(requirement["method_id"] or "") != BROWSER_INSPECTION_METHOD_ID:
        raise CapturedInspectionReviewError(AGENT_IS_NOT_A_BROWSER_CAPTURE_RUNNER)
    path = str(requirement["verdict_path"] or "")
    if path and path != AGENT_VERDICT_PATH:
        raise CapturedInspectionReviewError(AGENT_IS_NOT_A_BROWSER_CAPTURE_RUNNER)
    capture = query_one(
        conn,
        "SELECT id FROM qa_runs "
        f"WHERE qa_requirement_id={p} AND performed_by='browser_substrate' "
        "AND execution_status='captured' "
        f"AND case_outcome IN ({p}, 'passed') AND completed_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (int(requirement_id), NEEDS_REVIEW_OUTCOME),
    )
    if capture is None:
        raise CapturedInspectionReviewError(CAPTURED_INSPECTION_REVIEW_RECOVERY)
    now = iso8601_now()
    roster = [
        {"requirement_id": int(requirement_id), "capture_run_id": int(capture["id"])}
    ]
    encoded = json.dumps(roster, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    execution_id = str(uuid4())
    item_id = requirement["item_id"]
    deployment_run_id = requirement["deployment_run_id"]
    if item_id is not None:
        transition = str(requirement["workflow_transition_id"] or "").strip() or (
            "verification"
        )
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,transition_id,actor_id,session_id,roster_digest,"
            "roster_json,cursor_ordinal,state,created_at,heartbeat_at,"
            f"completed_at) VALUES({', '.join([p] * 12)})",
            (
                execution_id,
                int(item_id),
                transition,
                str(actor_id or ""),
                str(session_id or "record-verdict"),
                digest,
                encoded,
                1,
                "completed",
                now,
                now,
                now,
            ),
        )
    elif deployment_run_id:
        conn.execute(
            "INSERT INTO qa_plan_executions("
            "id,deployment_run_id,actor_id,session_id,roster_digest,"
            "roster_json,cursor_ordinal,state,created_at,heartbeat_at,"
            f"completed_at) VALUES({', '.join([p] * 11)})",
            (
                execution_id,
                str(deployment_run_id),
                str(actor_id or ""),
                str(session_id or "record-verdict"),
                digest,
                encoded,
                1,
                "completed",
                now,
                now,
                now,
            ),
        )
    else:
        raise CapturedInspectionReviewError(CAPTURED_INSPECTION_REVIEW_RECOVERY)
    bundle_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_review_bundles("
        "id,execution_id,roster_digest,bundle_digest,bundle_json,state,"
        "reviewer_actor_id,reviewer_session_id,created_at,reviewed_at"
        f") VALUES({', '.join([p] * 10)})",
        (
            bundle_id,
            execution_id,
            digest,
            digest,
            encoded,
            "completed",
            str(actor_id or ""),
            str(session_id or "record-verdict"),
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO qa_plan_review_verdicts("
        "bundle_id,requirement_id,capture_run_id,review_run_id,verdict,"
        f"rationale,created_at) VALUES({', '.join([p] * 7)})",
        (
            bundle_id,
            int(requirement_id),
            int(capture["id"]),
            int(review_run_id),
            verdict,
            rationale or "captured inspection reviewed",
            now,
        ),
    )
    from yoke_core.domain.qa_capture_settlement import stamp_reviewed_capture

    stamp_reviewed_capture(
        conn,
        {"capture_run_id": int(capture["id"])},
        verdict=verdict,
        rationale=rationale or "captured inspection reviewed",
        created_at=now,
    )


__all__ = [
    "AGENT_IS_NOT_A_BROWSER_CAPTURE_RUNNER",
    "CAPTURED_INSPECTION_REVIEW_RECOVERY",
    "CapturedInspectionReviewError",
    "attach_agent_review_to_capture",
]
