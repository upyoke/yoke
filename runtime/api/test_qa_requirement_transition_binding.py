"""Lifecycle binding on the typed QA requirement authoring surface."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_requirement_create import (
    handle_qa_requirement_add,
    handle_qa_requirement_add_batch,
)
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import publish_workflow_version
from yoke_core.domain import qa
from yoke_core.domain import qa_requirements
from yoke_core.domain import workflow_item_binding_lock


def _request(item_id: int, transition_id: str | None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="1", session_id="dash-session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "method_id": "browser-check",
            "qa_phase": "verification",
            "instructions": "Inspect the workflow card in its actual route.",
            "expected_outcome": "The workflow card matches its visual contract.",
            "method_config": {
                "steps": [
                    {"action": "navigate", "route": "/workflows"},
                    {
                        "action": "assert",
                        "target": "main",
                        "check": "visible",
                    },
                ],
            },
            "workflow_transition_id": transition_id,
        },
    )


def test_requirement_persists_a_valid_pinned_workflow_transition():
    with test_database() as conn:
        insert_item(conn, id=2401, workflow_id="blitz")
        outcome = handle_qa_requirement_add(
            _request(2401, " done "),
        )
        assert outcome.primary_success is True
        row = conn.execute(
            "SELECT workflow_transition_id FROM qa_requirements WHERE id=%s",
            (outcome.result_payload["requirement_id"],),
        ).fetchone()
    assert row[0] == "done"


def test_requirement_rejects_a_transition_outside_the_pinned_workflow():
    with test_database() as conn:
        insert_item(conn, id=2402, workflow_id="blitz")
        outcome = handle_qa_requirement_add(
            _request(2402, "planned"),
        )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.workflow_transition_id"


def test_requirement_rejects_a_missing_workflow_transition():
    with test_database() as conn:
        insert_item(conn, id=2403, workflow_id="blitz")
        outcome = handle_qa_requirement_add(_request(2403, None))
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "is required" in outcome.error.message


def test_requirement_rejects_a_missing_pinned_parent():
    with test_database():
        outcome = handle_qa_requirement_add(_request(2499, "done"))
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "does not exist" in outcome.error.message


def test_requirement_batch_rejects_a_missing_workflow_transition():
    with test_database() as conn:
        insert_item(conn, id=2405, workflow_id="blitz")
        single = _request(2405, None)
        batch = FunctionCallRequest(
            function="qa.requirement.add_batch",
            actor=single.actor,
            target=single.target,
            payload={"rows": [dict(single.payload)]},
        )
        outcome = handle_qa_requirement_add_batch(batch)
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "is required" in outcome.error.message


def test_requirement_rejects_a_stage_without_a_qa_gate():
    with test_database() as conn:
        definition = deepcopy(builtin_workflow_definition("blitz")["definition"])
        definition["stages"][0]["label"] = "No QA enforcement"
        for stage in definition["stages"]:
            stage["gates"] = [
                gate for gate in stage["gates"] if gate["id"] != "qa_verification"
            ]
        publish_workflow_version(
            conn,
            workflow_id="blitz",
            definition=definition,
        )
        insert_item(conn, id=2404, workflow_id="blitz")
        outcome = handle_qa_requirement_add(
            _request(2404, "reviewing-implementation"),
        )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "no reachable qa_verification gate" in outcome.error.message


def test_requirement_accepts_only_stages_at_or_before_the_qa_gate():
    with test_database() as conn:
        definition = deepcopy(builtin_workflow_definition("blitz")["definition"])
        done_stage = definition["stages"][-1]
        qa_gate = next(
            gate for gate in done_stage["gates"] if gate["id"] == "qa_verification"
        )
        done_stage["gates"] = [
            gate for gate in done_stage["gates"] if gate["id"] != "qa_verification"
        ]
        definition["stages"][-2]["gates"].append(qa_gate)
        publish_workflow_version(
            conn,
            workflow_id="blitz",
            definition=definition,
        )
        insert_item(conn, id=2406, workflow_id="blitz")

        accepted = handle_qa_requirement_add(
            _request(2406, "reviewing-implementation"),
        )
        rejected = handle_qa_requirement_add(
            _request(2406, "done"),
        )

    assert accepted.primary_success is True
    assert rejected.primary_success is False
    assert "no reachable qa_verification gate" in rejected.error.message


def test_domain_cli_item_requirement_persists_transition():
    with test_database() as conn:
        insert_item(conn, id=2410, workflow_id="blitz")
        requirement_id = qa.cmd_requirement_add(
            item_id=2410,
            qa_kind="implementation_review",
            qa_phase="verification",
            workflow_transition_id=" done ",
        )
        row = conn.execute(
            "SELECT workflow_transition_id FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    assert row[0] == "done"


def test_domain_cli_locks_parent_before_transition_validation(monkeypatch):
    observed = []
    original_lock = workflow_item_binding_lock.lock_item_workflow_bindings
    original_validate = qa_requirements.require_cli_workflow_transition

    def record_lock(conn, item_ids):
        observed.append(("lock", tuple(item_ids)))
        return original_lock(conn, item_ids)

    def record_validation(conn, **kwargs):
        observed.append(("validate", kwargs["item_id"]))
        return original_validate(conn, **kwargs)

    monkeypatch.setattr(
        workflow_item_binding_lock,
        "lock_item_workflow_bindings",
        record_lock,
    )
    monkeypatch.setattr(
        qa_requirements,
        "require_cli_workflow_transition",
        record_validation,
    )
    with test_database() as conn:
        insert_item(conn, id=2415, workflow_id="blitz")
        qa.cmd_requirement_add(
            item_id=2415,
            qa_kind="implementation_review",
            qa_phase="verification",
            workflow_transition_id="done",
        )

    assert observed == [("lock", (2415,)), ("validate", 2415)]


def test_domain_cli_epic_task_requirement_uses_parent_pin():
    with test_database() as conn:
        insert_item(conn, id=2411, workflow_id="epic")
        insert_epic_task(conn, epic_id=2411, task_num=1)
        requirement_id = qa.cmd_requirement_add(
            epic_id=2411,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
            workflow_transition_id="reviewed-implementation",
        )
        row = conn.execute(
            "SELECT workflow_transition_id FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    assert row[0] == "reviewed-implementation"


def test_domain_cli_item_requirement_rejects_missing_transition():
    with test_database() as conn:
        insert_item(conn, id=2412, workflow_id="dash")
        with pytest.raises(SystemExit, match="2"):
            qa.cmd_requirement_add(
                item_id=2412,
                qa_kind="implementation_review",
                qa_phase="verification",
            )
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE item_id=2412"
        ).fetchone()[0]
    assert count == 0


def test_domain_cli_batch_validates_each_parent_transition(tmp_path):
    rows = [
        {
            "item_id": 2413,
            "qa_kind": "implementation_review",
            "qa_phase": "verification",
            "workflow_transition_id": "done",
        },
        {
            "epic_id": 2414,
            "task_num": 1,
            "qa_kind": "implementation_review",
            "qa_phase": "verification",
            "workflow_transition_id": "reviewed-implementation",
        },
    ]
    payload = tmp_path / "requirements.json"
    payload.write_text(json.dumps(rows), encoding="utf-8")
    with test_database() as conn:
        insert_item(conn, id=2413, workflow_id="blitz")
        insert_item(conn, id=2414, workflow_id="epic")
        insert_epic_task(conn, epic_id=2414, task_num=1)
        requirement_ids = qa.cmd_requirement_add_batch(json_file=str(payload))
        transitions = conn.execute(
            "SELECT workflow_transition_id FROM qa_requirements "
            "WHERE id = ANY(%s) ORDER BY id",
            (requirement_ids,),
        ).fetchall()
    assert [row[0] for row in transitions] == [
        "done",
        "reviewed-implementation",
    ]


def test_domain_cli_batch_rolls_back_when_a_transition_is_missing(tmp_path):
    rows = [
        {
            "item_id": 2416,
            "qa_kind": "implementation_review",
            "qa_phase": "verification",
            "workflow_transition_id": "done",
        },
        {
            "item_id": 2416,
            "qa_kind": "implementation_review",
            "qa_phase": "verification",
        },
    ]
    payload = tmp_path / "missing-transition.json"
    payload.write_text(json.dumps(rows), encoding="utf-8")
    with test_database() as conn:
        insert_item(conn, id=2416, workflow_id="blitz")
        with pytest.raises(SystemExit, match="2"):
            qa.cmd_requirement_add_batch(json_file=str(payload))
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE item_id=2416"
        ).fetchone()[0]
    assert count == 0


def test_domain_cli_deployment_run_requirement_needs_no_transition():
    with test_database():
        requirement_id = qa.cmd_requirement_add(
            deployment_run_id="run-unbound",
            qa_kind="post_deploy",
            qa_phase="post_deploy",
        )
    assert requirement_id > 0
