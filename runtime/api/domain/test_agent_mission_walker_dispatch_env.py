"""Walker dispatch: walk and copy commands ride the connection, walk-start names its run."""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import agent_mission_recording, agent_mission_walk_cli
from yoke_core.domain import machine_qa_mission_walk, qa_plan_execution_cli
from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract

EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"
FLAGS = f"--item ITEM-{4550} --execution-id {EXECUTION_ID} --requirement-id 18152"


def _bundle() -> dict:
    return {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": EXECUTION_ID,
        "subject": {"public_ref": f"ITEM-{4550}", "deployment_run_id": None},
        "execution_target": {
            "project": {"id": 1, "slug": "yoke"},
            "environment": {"name": "stage"},
            "tenant": {"slug": "yoke"},
            "endpoints": {"base_url": "https://stage.example"},
        },
        "execution_target_digest": "e" * 64,
        "cases": [
            {
                "requirement_id": 18152,
                "capture_runner": "agent_mission",
                "capture_run_id": 991,
                "executor": "informed_subagent",
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }


def test_walk_commands_carry_the_connection_env_in_field_and_prompt() -> None:
    dispatch = agent_mission_dispatch_contract(_bundle())
    result = {"review_bundle": {"dispatch": dispatch}}
    with (
        mock.patch.object(
            qa_plan_execution_cli, "_review_connection_env", return_value="prod"
        ),
        mock.patch.object(qa_plan_execution_cli, "_require_walker_dispatch_capability"),
    ):
        qa_plan_execution_cli._qualify_review_dispatch(result)
    walker = dispatch["walker_dispatches"][0]
    assert (
        walker["walk_start_command"] == f"yoke --env prod qa mission walk-start {FLAGS}"
    )
    assert walker["walk_end_command"] == (
        f"yoke --env prod qa mission walk-end {FLAGS} --run-id 991"
    )
    assert walker["walk_start_command"] in walker["prompt"]
    assert walker["walk_end_command"] in walker["prompt"]
    assert "yoke qa mission walk-" not in walker["prompt"]
    assert walker["host_copy_command"] == (
        f"yoke --env prod qa mission host-copy {FLAGS} "
        "--from TARGET_PATH --to LOCAL_PATH"
    )
    assert f"`{walker['host_copy_command']}`" in walker["prompt"]
    assert "`yoke qa mission host-copy" not in walker["prompt"]
    assert "connected-machine" not in walker["prompt"]
    assert "Clean up everything the walk creates" in walker["prompt"]
    assert "walker_dispatches[].prompt to its walker unchanged" in dispatch["prompt"]


def test_walk_start_output_names_the_capture_run(monkeypatch, capsys) -> None:
    def resolve(parsed, *, prog):
        parsed.mission_run_id = 991
        return {"contract": "issued"}

    monkeypatch.setattr(agent_mission_walk_cli, "resolve_mission_contract", resolve)
    monkeypatch.setattr(agent_mission_walk_cli, "_register", lambda: None)
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "execute_agent_mission_walk_start",
        lambda contract: {"lease_id": 7, "preparation": {"ok": True}},
    )
    assert agent_mission_walk_cli.main(["start", *FLAGS.split()]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == 991


def test_mission_access_reads_the_recorded_capture_run(monkeypatch) -> None:
    rows = [
        {"requirement_id": 18151, "result": {"run_id": 990}},
        {"requirement_id": 18152, "result": {"run_id": 991}},
    ]
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_store.result_rows", lambda conn, eid: rows
    )
    assert agent_mission_recording._mission_run_id(None, EXECUTION_ID, 18152) == 991
    assert agent_mission_recording._mission_run_id(None, EXECUTION_ID, 18153) is None
