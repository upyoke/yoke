"""Walker briefs name the deployment run, environment and commit a release walk tests."""

from __future__ import annotations

import copy

from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract

SHA = "0123456789abcdef0123456789abcdef01234567"


def _bundle(*, deployment: dict | None, os_config: dict | None) -> dict:
    target = {
        "project": {"id": 1, "slug": "yoke"},
        "environment": {"name": "prod"},
        "tenant": {"slug": "yoke"},
        "endpoints": {"base_url": "https://prod.example"},
    }
    if deployment is not None:
        target["deployment"] = deployment
    return {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": "01JQ8P4Z9K2M7V6T5R3N1B0AXY",
        "subject": {"public_ref": "ITEM-1", "deployment_run_id": None},
        "execution_target": target,
        "execution_target_digest": "e" * 64,
        "cases": [
            {
                "requirement_id": 18152,
                "capture_runner": "agent_mission",
                "method_config": copy.deepcopy(os_config or {}),
                "capture_run_id": 991,
                "executor": "informed_subagent",
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }


def _prompt(bundle: dict) -> str:
    return agent_mission_dispatch_contract(bundle)["walker_dispatches"][0]["prompt"]


RUN = {"run_id": "run-20261113-004", "release_lineage": SHA, "stage": "item-qa"}


def test_host_walk_names_deployment_run_environment_and_commit() -> None:
    prompt = _prompt(_bundle(deployment=RUN, os_config={"os": "macos"}))
    assert prompt.startswith(
        f"This walk tests deployment run run-20261113-004, environment prod, "
        f"commit {SHA}. The --run-id in the commands below is this walk's "
        "capture run, not the deployment run. "
    )
    assert "--run-id 991" in prompt


def test_controller_walk_names_deployment_run_environment_and_commit() -> None:
    prompt = _prompt(_bundle(deployment=RUN, os_config=None))
    assert prompt.startswith("This walk tests deployment run run-20261113-004")
    assert f"commit {SHA}" in prompt
    assert "Explore this mission on the controller" in prompt


def test_walk_outside_a_deployment_run_names_no_deployment_run() -> None:
    for os_config in ({"os": "macos"}, None):
        prompt = _prompt(_bundle(deployment=None, os_config=os_config))
        assert "deployment run" not in prompt
