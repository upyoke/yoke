"""Bounded PROCEED adjudication on an actual retained simulation attempt.

The item retains this discharge audit in its existing structured records. It is separate from
QA pass and waiver, and becomes inapplicable when a newer attempt is recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from yoke_contracts.timestamps import format_instant

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.item_json_sections import (
    SIMULATION_TRIAGE_SECTION,
    read_json_section,
    upsert_json_section,
)
from yoke_core.domain.events_acting_identity import resolve_acting_event_identity
from yoke_core.domain.qa_latest_execution import (
    latest_execution_id_sql,
    latest_executions,
)
from yoke_core.domain.qa_requirement_scope import lock_requirement_scope
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.sql_json import json_get
from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit

TRIAGE_EVENT = "QaSimulationTriaged"
TRIAGE_SECTION = SIMULATION_TRIAGE_SECTION


def triage_discharge_sql(conn: Any, alias: str = "") -> str:
    """Grade the owner-attested receipt against the exact selected capture.

    Exact raw bytes are stronger than a digest comparison and need no extra
    database extension. Actor, claim and report authorization are established
    by the only writer; neither generic sections nor event history owns them.
    """
    if not _table_exists(conn, "item_sections"):
        return "FALSE"
    q = alias or "qa_requirements"
    current = latest_execution_id_sql(q + ".id")

    def value(field: str) -> str:
        return json_get("triage.content", "$." + field)

    return (
        f"({q}.qa_kind='simulation' AND {q}.deployment_run_id IS NULL AND EXISTS("
        "SELECT 1 FROM item_sections triage JOIN qa_runs capture "
        f"ON capture.id=({current}) WHERE "
        f"triage.item_id={q}.item_id AND triage.section_name='{TRIAGE_SECTION} ' "
        f"|| CAST({q}.id AS TEXT) || ':' || CAST(capture.id AS TEXT) "
        f"AND {value('actor_id')} IS NOT NULL AND {value('claim_id')} IS NOT NULL "
        f"AND {value('session_id')} IS NOT NULL "
        f"AND {value('discharge_kind')}='simulation_triage' "
        f"AND {value('recommendation')}='PROCEED' "
        f"AND CAST({value('requirement_id')} AS TEXT)=CAST({q}.id AS TEXT) "
        f"AND CAST({value('run_id')} AS TEXT)=CAST(capture.id AS TEXT) "
        f"AND CAST({value('capture_run_id')} AS TEXT)=CAST(capture.id AS TEXT) "
        "AND capture.verdict='fail' AND capture.completed_at IS NOT NULL "
        "AND COALESCE(capture.case_outcome,'failed') NOT IN ('running','waiting') "
        f"AND CAST(capture.raw_result AS TEXT)={value('report_raw_result')} "
        f"AND CAST(capture.started_at AS TIMESTAMPTZ)=CAST({value('capture_started_at')} AS TIMESTAMPTZ) "
        f"AND CAST(capture.completed_at AS TIMESTAMPTZ)=CAST({value('capture_completed_at')} AS TIMESTAMPTZ)))"
    )


def current_simulation_triage(conn: Any, requirement_id: int) -> dict[str, Any] | None:
    """Return durable discharge proof independently of event retention."""
    settled = query_one(
        conn,
        f"SELECT {triage_discharge_sql(conn, 'q')} AS settled FROM qa_requirements q WHERE id=%s",
        (requirement_id,),
    )
    if not settled or not settled["settled"]:
        return None
    attempt = latest_executions(conn, [requirement_id]).get(requirement_id)
    if attempt is None or attempt["verdict"] != "fail" or not attempt["completed_at"]:
        return None
    requirement = query_one(
        conn,
        "SELECT item_id,qa_kind,deployment_run_id FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    )
    if (
        requirement is None
        or requirement["qa_kind"] != "simulation"
        or requirement["deployment_run_id"]
    ):
        return None
    receipt = read_json_section(
        conn,
        item_id=int(requirement["item_id"]),
        section=f"{TRIAGE_SECTION} {requirement_id}:{attempt['id']}",
    )
    if (
        not receipt
        or not receipt.get("actor_id")
        or receipt.get("requirement_id") != requirement_id
        or receipt.get("run_id") != attempt["id"]
        or receipt.get("discharge_kind") != "simulation_triage"
        or receipt.get("report_digest")
        != hashlib.sha256(str(attempt["raw_result"]).encode()).hexdigest()
    ):
        return None
    return receipt


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
    identity = resolve_acting_event_identity(TRIAGE_EVENT, conn=conn)
    if identity is None or identity.actor_id is None:
        raise ValueError(
            "simulation_triage_actor_missing: bind the acting session to its authorized actor before PROCEED"
        )
    claim = get_claim_for_work_unit(conn, item_id=str(epic_id))
    if (
        not claim
        or claim["session_id"] != identity.session_id
        or (session_id and session_id != identity.session_id)
    ):
        raise ValueError(
            "simulation_triage_claim_required: the authenticated acting session must hold the epic work claim"
        )
    section = f"{TRIAGE_SECTION} {requirement_id}:{attempt['id']}"
    retained = read_json_section(conn, item_id=epic_id, section=section)
    prior = current_simulation_triage(conn, requirement_id)
    reason = (
        rationale
        or "Accepted noncritical gaps from the report's explicit PROCEED recommendation"
    )
    if retained is not None and prior is None:
        raise ValueError(
            "simulation_triage_attempt_changed: the retained discharge cannot be overwritten after capture mutation; record a new actual attempt"
        )
    if prior is not None:
        if prior["filed_public_refs"] != refs or prior["rationale"] != reason:
            raise ValueError(
                "simulation_triage_replay_conflict: the exact attempt already has a different discharge"
            )
        return prior
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    detail = {
        "requirement_id": requirement_id,
        "actor_id": identity.actor_id,
        "session_id": identity.session_id,
        "claim_id": int(claim["id"]),
        "report_raw_result": str(attempt["raw_result"]),
        "capture_started_at": format_instant(attempt["started_at"]),
        "capture_completed_at": format_instant(attempt["completed_at"]),
        "rationale": reason,
        "recorded_at": iso8601_now(),
        "run_id": int(attempt["id"]),
        "capture_run_id": int(attempt["id"]),
        "discharge_kind": "simulation_triage",
        "recommendation": "PROCEED",
        "filed_public_refs": refs,
        "report_digest": hashlib.sha256(
            str(attempt["raw_result"]).encode()
        ).hexdigest(),
    }
    upsert_json_section(
        conn,
        item_id=epic_id,
        section=section,
        payload=detail,
        ordering=245,
    )
    receipt = current_simulation_triage(conn, requirement_id)
    if receipt is None:
        raise ValueError(
            "simulation_triage_audit_unavailable: durable item receipt was not recorded; no handoff"
        )
    conn.commit()
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
    )
    return receipt
