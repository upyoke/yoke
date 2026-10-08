"""Bounded PROCEED adjudication on an actual retained simulation attempt.

The existing event ledger retains this discharge audit. It is separate from
QA pass and waiver, and becomes inapplicable when a newer attempt is recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_latest_execution import (
    latest_execution_id_sql,
    latest_executions,
)
from yoke_core.domain.qa_requirement_scope import lock_requirement_scope
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.sql_json import json_get

TRIAGE_EVENT = "QaSimulationTriaged"


def triage_discharge_sql(conn: Any, alias: str = "") -> str:
    """Only an authenticated audit for the selected actual report discharges it."""
    if not _table_exists(conn, "events"):
        return "FALSE"
    q = alias or "qa_requirements"
    requirement = json_get("triage.envelope", "$.context.detail.requirement_id")
    run = json_get("triage.envelope", "$.context.detail.run_id")
    kind = json_get("triage.envelope", "$.context.detail.discharge_kind")
    return (
        f"({q}.qa_kind='simulation' AND {q}.deployment_run_id IS NULL AND EXISTS("
        "SELECT 1 FROM events triage WHERE "
        f"triage.event_name='{TRIAGE_EVENT}' AND triage.event_type='qa_lifecycle' "
        "AND triage.source_type='system' AND triage.actor_id IS NOT NULL "
        f"AND triage.item_id=CAST({q}.item_id AS TEXT) "
        f"AND CAST({requirement} AS TEXT)=CAST({q}.id AS TEXT) "
        f"AND {kind}='simulation_triage' "
        f"AND CAST({run} AS TEXT)=CAST(({latest_execution_id_sql(q + '.id')}) AS TEXT)))"
    )


def current_simulation_triage(conn: Any, requirement_id: int) -> dict[str, Any] | None:
    """Return the separate discharge receipt, never a fabricated passing run."""
    attempt = latest_executions(conn, [requirement_id]).get(requirement_id)
    if attempt is None:
        return None
    row = query_one(
        conn,
        f"SELECT triage.event_id,triage.actor_id,triage.envelope FROM qa_requirements q "
        "JOIN events triage ON triage.event_name=%s "
        f"AND CAST({json_get('triage.envelope', '$.context.detail.requirement_id')} AS TEXT)=CAST(q.id AS TEXT) "
        f"AND CAST({json_get('triage.envelope', '$.context.detail.run_id')} AS TEXT)=%s "
        f"WHERE q.id=%s AND {triage_discharge_sql(conn, 'q')} "
        "AND triage.actor_id IS NOT NULL ORDER BY triage.id DESC LIMIT 1",
        (TRIAGE_EVENT, str(attempt["id"]), requirement_id),
    )
    if row is None:
        return None
    envelope = (
        json.loads(row["envelope"])
        if isinstance(row["envelope"], str)
        else row["envelope"]
    )
    return {
        **envelope["context"]["detail"],
        "event_id": row["event_id"],
        "actor_id": row["actor_id"],
    }


def _report_fields(attempt: dict[str, Any]) -> tuple[str, int]:
    raw = attempt["raw_result"]
    payload = json.loads(raw) if isinstance(raw, str) else raw
    body = str(payload.get("body") or "") if isinstance(payload, dict) else ""
    recommendations = re.findall(
        r"^[-*]?\s*Recommendation:\s*([A-Z_-]+)", body, re.MULTILINE
    )
    critical = re.search(
        r"\[CRITICAL\]|^###\s*CRITICAL|\b[1-9][0-9]* critical\b",
        body,
        re.IGNORECASE | re.MULTILINE,
    )
    if (
        critical
        or not recommendations
        or any(value != "PROCEED" for value in recommendations)
    ):
        raise ValueError(
            "simulation_triage_not_authorized: the current report must explicitly recommend PROCEED with zero CRITICAL gaps"
        )
    headings = len(re.findall(r"^###\s+GAP #", body, re.MULTILINE))
    counts = [int(value) for value in re.findall(r"Gaps Found:\s*(\d+)", body)]
    return body, max([headings, *counts])


def record_simulation_triage(
    conn: Any,
    epic_id: int,
    *,
    recommendation: str,
    rationale: str,
    filed_public_refs: list[str],
    session_id: str | None,
) -> dict[str, Any]:
    """Extend the existing PROCEED owner with a durable exact-attempt discharge."""
    if recommendation != "PROCEED":
        raise ValueError(
            "simulation_triage_not_authorized: other recommendations require the existing operator decision"
        )
    requirements = query_rows(
        conn,
        "SELECT q.id,i.project_id FROM qa_requirements q JOIN items i ON i.id=q.item_id "
        f"WHERE q.item_id=%s AND q.qa_kind='simulation' AND {json_get('q.success_policy', '$.phase')}='integration'",
        (epic_id,),
    )
    if len(requirements) != 1:
        raise ValueError(
            "No integration simulation requirement, or ambiguous simulation scope; inspect the retained reports"
        )
    requirement_id = int(requirements[0]["id"])
    lock_requirement_scope(conn, requirement_id)
    attempt = latest_executions(conn, [requirement_id]).get(requirement_id)
    if attempt is None or attempt["verdict"] != "fail" or not attempt["completed_at"]:
        raise ValueError(
            "simulation_triage_not_authorized: only a completed failed simulation can be triaged"
        )
    _body, required = _report_fields(attempt)
    refs = sorted(set(filed_public_refs))
    if len(refs) < required:
        raise ValueError(
            "simulation_triage_followups_missing: file each required gap before PROCEED"
        )
    if refs:
        rows = query_rows(
            conn,
            "SELECT ir.public_ref FROM item_refs ir JOIN items i ON i.id=ir.item_id "
            f"WHERE ir.public_ref IN ({','.join('%s' for _ in refs)}) AND i.project_id=%s AND i.id<>%s",
            (*refs, requirements[0]["project_id"], epic_id),
        )
        if {str(row["public_ref"]) for row in rows} != set(refs):
            raise ValueError(
                "simulation_triage_followups_invalid: filed refs must exist in the epic's project"
            )
    prior = current_simulation_triage(conn, requirement_id)
    reason = (
        rationale
        or "Accepted noncritical gaps from the report's explicit PROCEED recommendation"
    )
    if prior is not None:
        if prior["filed_public_refs"] != refs or prior["rationale"] != reason:
            raise ValueError(
                "simulation_triage_replay_conflict: the exact attempt already has a different discharge"
            )
        return prior
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    detail = {
        "run_id": int(attempt["id"]),
        "capture_run_id": int(attempt["id"]),
        "discharge_kind": "simulation_triage",
        "recommendation": "PROCEED",
        "filed_public_refs": refs,
        "report_digest": hashlib.sha256(
            str(attempt["raw_result"]).encode()
        ).hexdigest(),
    }
    emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name=TRIAGE_EVENT,
        requirement_id=requirement_id,
        qa_kind="simulation",
        qa_phase="verification",
        rationale=reason,
        source="agent",
        extra_detail=detail,
        transactional=True,
    )
    receipt = current_simulation_triage(conn, requirement_id)
    if receipt is None:
        raise ValueError(
            "simulation_triage_audit_unavailable: authenticated durable discharge was not recorded; no handoff"
        )
    conn.commit()
    return receipt
