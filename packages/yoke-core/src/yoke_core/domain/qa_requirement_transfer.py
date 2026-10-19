"""Transfer one unexecuted direct case with an audit on both items."""

from __future__ import annotations
from typing import Any

from yoke_core.domain.db_helpers import query_one, iso8601_now
from yoke_core.domain.item_json_sections import upsert_json_section
from yoke_core.domain.qa_requirement_proof import proof_refusal
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings
from yoke_core.domain.qa_workflow_binding_validation import validate_item_qa_transition


def transfer_requirement(
    conn: Any,
    *,
    requirement_id: int,
    destination: str,
    transition: str,
    rationale: str,
    session_id: str,
    request_id: str,
) -> dict[str, Any]:
    """Move in the caller's transaction; preserve immutable execution history."""

    def refuse(reason: str, recovery: str) -> None:
        raise ValueError(f"requirement_transfer_refused: {reason}. {recovery}")

    if not rationale.strip():
        refuse(
            "a transfer needs a rationale", "Explain why the destination owns this case"
        )
    dest = query_one(
        conn,
        "SELECT i.id,i.project_id,i.status FROM items i JOIN item_refs r ON r.item_id=i.id WHERE r.public_ref=%s",
        (destination,),
    )
    row = query_one(
        conn, "SELECT * FROM qa_requirements WHERE id=%s", (requirement_id,)
    )
    if dest is None or row is None:
        refuse(
            "requirement or destination missing", "Read both identities before retrying"
        )
    row = dict(row)
    source_id = row.get("item_id")
    if source_id is None or row.get("plan_id") or row.get("deployment_run_id"):
        refuse(
            "only a direct item case can move",
            "Attach the proving plan to the destination; keep frozen case history on its original subject",
        )
    destination_id = int(dest["id"])
    lock_item_workflow_bindings(conn, sorted({int(source_id), destination_id}))
    row = dict(
        query_one(
            conn,
            "SELECT * FROM qa_requirements WHERE id=%s FOR UPDATE",
            (requirement_id,),
        )
    )
    if row.get("item_id") != source_id:
        refuse(
            "ownership changed concurrently",
            "Read the requirement and retry with its current owner",
        )
    source = query_one(conn, "SELECT project_id FROM items WHERE id=%s", (source_id,))
    if source["project_id"] != dest["project_id"]:
        refuse(
            "items belong to different projects",
            "Create the receiving project's companion case instead",
        )
    if source_id == destination_id or dest["status"] in {
        "done",
        "cancelled",
        "stopped",
    }:
        refuse("destination is the same item or terminal", "Name a different open item")
    for item_id in (source_id, destination_id):
        claim = get_claim_for_work_unit(conn, item_id=str(item_id))
        if not claim or claim["session_id"] != session_id:
            refuse(
                f"no work claim on item {item_id}",
                "Hold both item work claims before transferring",
            )
    refusal = proof_refusal(
        row,
        subject=f"item {source_id}, requirement {requirement_id}",
        conn=conn,
        item_id=source_id,
    )
    if refusal:
        raise ValueError(refusal)
    if row.get("method_id") and not query_one(
        conn,
        "SELECT id FROM qa_methods WHERE id=%s AND runner_id<>''",
        (row["method_id"],),
    ):
        refuse(
            "the case method is not runnable",
            "Register its method before transferring the case",
        )
    if obligation_settled(row) or query_one(
        conn,
        "SELECT id FROM qa_runs WHERE qa_requirement_id=%s LIMIT 1",
        (requirement_id,),
    ):
        refuse(
            "settled or executed cases keep their subject",
            "Create an executable destination case; retain and settle the original explicitly",
        )
    from yoke_core.domain.runs import ACTIVE_RUN_STATUSES

    active_run = query_one(
        conn,
        "SELECT dri.run_id FROM deployment_run_items dri JOIN deployment_runs dr ON dr.id=dri.run_id WHERE dri.item_id=%s AND dr.status=ANY(%s) LIMIT 1",
        (source_id, list(ACTIVE_RUN_STATUSES)),
    )
    if active_run:
        refuse(
            "the source item belongs to an active deployment run",
            "Keep its frozen admission; settle or remove that membership through the run owner before transferring",
        )
    linked = query_one(
        conn,
        "SELECT id FROM qa_requirements WHERE replacement_requirement_id=%s OR superseded_by_requirement_id=%s OR plan_case_key=%s LIMIT 1",
        (requirement_id, requirement_id, f"admitted-requirement-{requirement_id}"),
    )
    if linked:
        refuse(
            "a correction or admitted copy refers to this case",
            "Keep its frozen subject; create a new executable destination case",
        )
    bound, _ = validate_item_qa_transition(
        conn,
        item_id=destination_id,
        transition_id=transition,
        method_id=row.get("method_id"),
        qa_phase=row["qa_phase"],
    )
    refusal = proof_refusal(
        dict(row, workflow_transition_id=bound),
        subject=destination,
        conn=conn,
        item_id=destination_id,
    )
    if refusal:
        raise ValueError(refusal)
    conn.execute(
        "UPDATE qa_requirements SET item_id=%s,workflow_transition_id=%s WHERE id=%s",
        (destination_id, bound, requirement_id),
    )
    receipt = dict(
        requirement_id=requirement_id,
        from_item_id=source_id,
        to_item_id=destination_id,
        workflow_transition_id=bound,
        rationale=rationale.strip(),
        session_id=session_id,
        transferred_at=iso8601_now(),
    )
    for item_id in (source_id, destination_id):
        upsert_json_section(
            conn,
            item_id=item_id,
            section=f"QA requirement transfer {request_id}",
            payload=receipt,
            ordering=210,
        )
    return receipt
