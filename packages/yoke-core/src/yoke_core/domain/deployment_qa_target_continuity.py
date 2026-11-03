"""Stored takeover evidence remains owned while fresh work advances receipts."""

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read
from yoke_core.domain.deployment_qa_takeover_identity import inherited_target
from yoke_core.domain.deployment_qa_target_reads import _decode_stored_target


def subject_rows(conn, run_id, stage_name, member_item_id):
    from yoke_core.domain.deployment_qa_presentation_facts import (
        subject_requirement_rows,
    )

    rows = subject_requirement_rows(conn, run_id, stage_name, member_item_id)
    if rows is not None:
        return rows
    return query_rows(
        conn,
        "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "ORDER BY id",
        (run_id, stage_name, int(member_item_id or 0)),
    )


def same_destination(left, right):
    from yoke_core.domain.deployment_qa_execution_target import _destination

    return _destination(left) == _destination(right)


def evidence_target_matches(conn, run_id, stored, current):
    return (
        not (current.get("deployment") or {}).get("shared_plan")
        and inherited_target(conn, run_id, stored)
        and same_destination(stored, current)
    )


def settlement_target(conn, subject, target):
    if subject.get("shared_plan"):
        return target
    from yoke_core.domain.qa_execution_environment_target import target_digest

    return presentation_read(
        conn,
        (
            "qa_settlement_target",
            str(subject["id"]),
            str(subject["stage"]["name"]),
            subject.get("member_item_id"),
            target_digest(target),
        ),
        lambda: _resolve_settlement_target(conn, subject, target),
    )


def _resolve_settlement_target(conn, subject, target):
    run_id = str(subject["id"])
    targets = [
        stored
        for row in subject_rows(
            conn, run_id, str(subject["stage"]["name"]), subject.get("member_item_id")
        )
        if row["method_id"] is not None
        and (stored := _decode_stored_target(row["execution_target_json"])) is not None
        and stored == target
    ]
    return max(
        targets,
        default=target,
        key=lambda stored: int(
            (stored.get("observation") or {}).get("receipt_id") or 0
        ),
    )


def evidence_cases(conn, *, run_id, stage_name, member_item_id, digest, target=None):
    rows = subject_rows(conn, run_id, stage_name, member_item_id)
    return [
        dict(row)
        for row in rows
        if row["method_id"] is not None
        and row["blocking_mode"] == "blocking"
        and row["execution_target_digest"] == digest
    ]


def refresh_target(conn, run_id, stage, member, stored):
    if not inherited_target(conn, run_id, stored):
        return stored
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    return deployment_qa_execution_target(
        conn,
        deployment_qa_stage_subject(
            conn,
            run_id=run_id,
            stage_name=stage,
            member_item_id=member,
            require_active=False,
        ),
    )


def same_owned_destination(predecessor, successor):
    """Already-owned deployment obligations compare destination, not provenance."""
    from yoke_core.domain.deployment_qa_execution_target import (
        is_deployment_execution_target,
    )

    run_id = predecessor.get("deployment_run_id")
    if not run_id or run_id != successor.get("deployment_run_id"):
        return False
    targets = [
        _decode_stored_target(row.get("execution_target_json"))
        for row in (predecessor, successor)
    ]
    from yoke_core.domain.qa_execution_environment_target import target_digest

    return all(
        target is not None
        and is_deployment_execution_target(target)
        and target_digest(target) == row.get("execution_target_digest")
        for row, target in zip((predecessor, successor), targets, strict=True)
    ) and same_destination(*targets)
