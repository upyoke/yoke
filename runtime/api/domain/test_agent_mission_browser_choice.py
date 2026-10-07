"""Mission walkers pick a browser that exists on the Test Machine."""

from __future__ import annotations

import pytest

from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract


EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


def _walker(executor: str) -> dict:
    bundle = {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": EXECUTION_ID,
        "subject": {"item_id": 4550, "deployment_run_id": None},
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
                "executor": executor,
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }
    return agent_mission_dispatch_contract(bundle)["walker_dispatches"][0]


@pytest.mark.parametrize("executor", ["naive_target_session", "informed_subagent"])
def test_walker_prompt_uses_yoke_browser_only_when_the_walk_installed_yoke(
    executor: str,
) -> None:
    walker = _walker(executor)
    prompt = walker["prompt"]

    assert "if Yoke is on the target because this walk installed it" in prompt
    assert walker["browser_setup_command"] in prompt
    assert walker["browser_step_command"] in prompt
    assert "Otherwise open the host's own browser" in prompt
    assert "Safari on macOS" in prompt
    assert "the desktop's default browser elsewhere" in prompt
    assert "screenshots and keystrokes" in prompt
    assert "Never install Yoke on a Test Machine to get a browser." in prompt
