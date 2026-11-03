"""Stored takeover evidence remains owned while fresh work advances receipts."""

import json
from collections.abc import Mapping

from yoke_core.domain.db_helpers import query_rows
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
    run_id = str(subject["id"])
    targets = [
        stored
        for row in subject_rows(
            conn, run_id, str(subject["stage"]["name"]), subject.get("member_item_id")
        )
        if row["method_id"] is not None
        and (stored := _decode_stored_target(row["execution_target_json"])) is not None
        and (stored == target or evidence_target_matches(conn, run_id, stored, target))
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
        and (
            row["execution_target_digest"] == digest
            or (
                target is not None
                and (stored := _decode_stored_target(row["execution_target_json"]))
                is not None
                and evidence_target_matches(conn, run_id, stored, target)
            )
        )
    ]


def link_inherited_replacements(conn, refresh, created):
    from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key
    from yoke_core.domain.qa_requirement_replacement import point_at_replacement

    for row in (
        query_rows(
            conn,
            "SELECT id,plan_id,plan_case_key,host_baseline FROM qa_requirements "
            "WHERE id=ANY(%s)",
            (created,),
        )
        if created
        else []
    ):
        for old in refresh.rows_by_plan[int(row["plan_id"])]:
            if (
                refresh.verdicts.get(int(old["id"])) == "fail"
                and old["host_baseline"] == row["host_baseline"]
                and base_case_key(old["plan_case_key"])
                == base_case_key(row["plan_case_key"])
            ):
                raw = old["execution_target_json"]
                stored = dict(raw) if isinstance(raw, Mapping) else json.loads(raw)
                if evidence_target_matches(
                    conn, refresh.run_id, stored, refresh.target
                ):
                    point_at_replacement(conn, int(old["id"]), int(row["id"]))


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


def require_fresh_materialization(conn, subject, target):
    from yoke_core.domain.qa_execution_environment_target import target_digest
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
    )

    run_id, stage = str(subject["id"]), str(subject["stage"]["name"])
    member = subject.get("member_item_id")
    rows = subject_rows(conn, run_id, stage, member)
    if any(row["execution_target_digest"] == target_digest(target) for row in rows):
        return
    if not any(
        (stored := _decode_stored_target(row["execution_target_json"])) is not None
        and evidence_target_matches(conn, run_id, stored, target)
        for row in rows
    ):
        return
    from yoke_core.domain.project_identity import render_item_ref

    scope = (
        f"--item {render_item_ref(conn, member)}"
        if member is not None
        else f"--deployment-run-id {run_id}"
    )
    raise QaPlanExecutionStateError(
        "qa_successor_target_not_materialized: the successor receipt is ready "
        "but cases still name its predecessor; preserve prior evidence and run "
        f"`yoke qa plan rematerialize {scope} --stage {stage}` before starting a fresh attempt"
    )
