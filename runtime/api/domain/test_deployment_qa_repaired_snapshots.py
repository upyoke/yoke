"""Replay reviewed snapshots against complete isolated run evidence.

Set YOKE_QA_SNAPSHOT_PROOF_DIR to the private capture directory. The ordinary
suite exercises synthetic contracts; original captures never enter Git.
"""

import json
import hashlib
from pathlib import Path

import pytest

from runtime.api.fixtures.captured_deployment_qa import (
    PROOF_DIR,
    capture_rows,
    digest_rows,
    read_capture,
    preserved as preserved,
)
from yoke_core.domain.deployment_qa_frozen_plan_selection import member_requirements
from yoke_core.domain.deployment_qa_plan_selection import selected_plans
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa
from yoke_core.domain.qa_plan_case_definition import (
    snapshot_fan_out,
    materialized_definition,
)

pytestmark = pytest.mark.skipif(
    not PROOF_DIR, reason="private reviewed capture input not selected"
)


def test_reviewed_images_keep_whole_run_contract_and_acceptance_read_only(preserved):
    conn, members, images, requirements = preserved
    protected = [
        "qa_requirements",
        "qa_runs",
        "qa_artifacts",
        "qa_plan_executions",
        "qa_plan_execution_results",
        "qa_plan_review_bundles",
        "qa_plan_review_verdicts",
        "deployment_runs",
        "deployment_run_items",
    ]
    before = {table: digest_rows(conn, table) for table in protected}
    count = 0
    expanded = 0
    matched_ids = set()
    answers = []
    for member in members:
        subject = deployment_qa_stage_subject(
            conn,
            run_id=member["run_id"],
            stage_name="item-qa",
            member_item_id=member["item_id"],
            require_active=False,
        )
        target = deployment_qa_execution_target(conn, subject)
        admitted = member_requirements(conn, subject, target=target)
        snapshots = selected_plans(
            conn,
            subject,
            agent_plan=None,
            target=target,
            admitted=admitted,
            allow_empty=True,
            lock_plans=False,
        )
        raw = subject["member_snapshot"]["plans"]
        selected = {int(snapshot["plan"]["id"]): snapshot for snapshot in snapshots}
        for snapshot in raw:
            if snapshot["attachment"]["qa_phase"] != "post_deploy":
                continue
            pid = int(snapshot["plan"]["id"])
            assert pid in selected, (
                member["run_id"],
                member["item_id"],
                pid,
                "omitted frozen plan",
            )
            assert selected[pid]["cases"] == snapshot["cases"]
            count += len(snapshot["cases"])
            fan_out = snapshot_fan_out(snapshot["plan"], snapshot["cases"])
            for case in snapshot["cases"]:
                for position, baseline in enumerate(fan_out[case["case_key"]], 1):
                    candidates = [
                        row
                        for row in requirements
                        if row["deployment_run_id"] == member["run_id"]
                        and row["plan_id"] == pid
                        and row["plan_case_key"] == case["case_key"]
                        and row["host_baseline"] == baseline
                        and row["deployment_member_item_id"]
                        in (None, member["item_id"])
                    ]
                    assert candidates, (
                        member["run_id"],
                        pid,
                        case["case_key"],
                        baseline,
                    )
                    row = next(
                        (
                            row
                            for row in candidates
                            if row["deployment_member_item_id"] is None
                        ),
                        candidates[0],
                    )
                    definition = materialized_definition(
                        plan=snapshot["plan"],
                        case=case,
                        qa_phase="post_deploy",
                        baseline=baseline,
                        baseline_position=position,
                        transition_id=row["workflow_transition_id"],
                        execution_target=json.loads(row["execution_target_json"]),
                        target_env=row["target_env"],
                    )
                    for key in definition:
                        actual, expected = definition[key], row[key]
                        if key in {
                            "success_policy",
                            "capability_requirements",
                            "method_config",
                            "execution_target_json",
                        }:
                            actual = (
                                json.loads(actual)
                                if isinstance(actual, str)
                                else actual
                            )
                            expected = (
                                json.loads(expected)
                                if isinstance(expected, str)
                                else expected
                            )
                        assert actual == expected, (
                            pid,
                            case["case_key"],
                            baseline,
                            key,
                        )
                    expanded += 1
                    matched_ids.add(row["id"])
        answer = current_item_qa(
            conn,
            run_id=member["run_id"],
            item_id=member["item_id"],
            current_stage=subject["current_stage"],
        )
        answers.append(
            {
                "run_id": member["run_id"],
                "item_id": member["item_id"],
                "accepted": answer.accepted,
                "blockers": list(answer.blockers),
            }
        )
    from yoke_core.domain.deployment_run_target_takeover import (
        _moving_members,
        _waiting_run,
    )

    stages = json.loads(capture_rows("original-flow-definition.json")[0]["stages"])
    compositions = []
    for run in capture_rows("run-protected-before.json"):
        moving = _moving_members(conn, {**run, "stages": stages}, False)
        expected = {
            answer["item_id"]
            for answer in answers
            if answer["run_id"] == run["id"]
            and not answer["accepted"]
            and next(
                member["status"]
                for member in members
                if member["item_id"] == answer["item_id"]
            )
            not in {"done", "cancelled", "stopped"}
        }
        assert {row["item_id"] for row in moving} == expected
        compositions.append({"run_id": run["id"], "moving_members": sorted(expected)})
    flow = capture_rows("original-flow-definition.json")[0]
    waiting = _waiting_run(
        conn,
        {
            "id": "isolated-successor",
            "project_id": flow["project_id"],
            "flow": flow["id"],
            "target_environment_id": flow["target_environment_id"],
        },
    )
    expected_waits = [
        row["id"]
        for row in capture_rows("run-protected-before.json")
        if row["current_stage"] == "item-qa"
    ]
    assert waiting["id"] in expected_waits
    preservation = read_capture("preservation-proof.json")
    assert count == preservation["case_definitions"]
    assert expanded == preservation["expanded_subject_obligations"]
    assert len(matched_ids) == preservation["unique_materialized_requirement_ids"]
    assert {table: digest_rows(conn, table) for table in protected} == before
    print(
        json.dumps(
            {
                "subjects": len(members),
                "selected_definitions": count,
                "expanded_obligations": expanded,
                "materialized_ids": sorted(matched_ids),
                "composition": compositions,
                "review_image_sha256": hashlib.sha256(
                    (Path(PROOF_DIR) / "review-document.json").read_bytes()
                ).hexdigest(),
                "acceptance": answers,
            },
            sort_keys=True,
        )
    )
