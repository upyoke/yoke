"""Reuse acceptance only while its target and all member QA facts still match.

The proof is captured after the full ladder succeeds. Requirement rewrites,
rematerialized cases and new verdicts change it, so old acceptance cannot hide
newly owed work. An acceptance without this proof requires the full ladder.
"""

import json

from yoke_core.domain.deployment_run_qa_fingerprint import member_acceptance_fingerprint
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
)


def _proof(conn, run_id, member):
    return member_acceptance_fingerprint(conn, run_id, member)


def _acceptance(conn, run_id, stage, member):
    return conn.execute(
        "SELECT r.id,r.verdict,r.raw_result,q.execution_target_digest FROM qa_runs r JOIN qa_requirements q "
        "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s "
        "AND q.deployment_stage=%s AND q.deployment_member_item_id=%s "
        "AND q.qa_kind=%s "
        "AND q.retracted_at IS NULL AND q.superseded_by_requirement_id IS NULL "
        "ORDER BY r.id DESC LIMIT 1",
        (str(run_id), str(stage), member, DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND),
    ).fetchone()


def acceptance_proof(conn, requirement_id):
    """Capture proof before inserting immutable acceptance evidence."""
    row = conn.execute(
        "SELECT deployment_run_id,deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    if row is None or row["deployment_member_item_id"] is None:
        return {}
    return {
        "member_qa_fingerprint": _proof(
            conn, str(row["deployment_run_id"]), int(row["deployment_member_item_id"])
        )
    }


def settled_member_status(conn, *, run_id, stage_name, member_item_id):
    """A cheap current acceptance, or None to request the full ladder."""
    if member_item_id is None:
        return None
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_target_continuity import settlement_target
    from yoke_core.domain.qa_execution_environment_target import target_digest
    from yoke_core.domain.deployment_qa_stage_outcome import passed

    row = _acceptance(conn, run_id, stage_name, member_item_id)
    if row is None or row["verdict"] != "pass":
        return None
    raw = json.loads(str(row["raw_result"] or "{}"))
    proof = raw.get("member_qa_fingerprint")
    if not proof:
        return None
    subject = deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name=stage_name, member_item_id=member_item_id
    )
    target = settlement_target(
        conn, subject, deployment_qa_execution_target(conn, subject)
    )
    digest = target_digest(target)
    if row["execution_target_digest"] != digest or proof != _proof(conn, run_id, member_item_id):
        return None
    return {**passed(), "target_digest": digest}
