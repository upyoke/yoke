"""The QA launch recipes reach the real create parser as itemless requests."""

import re
import shlex
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import session_control_launches
from yoke_core.domain.deployment_qa_stage_wake import stage_wait_message
from yoke_core.domain.merge_queue_landing_notice import HOLDER
from yoke_core.domain.qa_partition_launch_recipe import partition_launch_recipe


def _launch_args(command):
    words = shlex.split(command)
    return words[words.index("create") + 1 :]


def _parse_launch(args):
    with (
        patch.object(session_control_launches, "read_stdin_payload", return_value="Walk the exact partition."),
        patch.object(session_control_launches, "_dispatch_launch", return_value=0) as dispatch,
    ):
        assert session_control_launches.session_launch_create(args) == 0
    assert dispatch.call_args.kwargs["function_id"] == "session_control.launch.create"
    payload = dispatch.call_args.kwargs["payload"]
    assert "item" not in payload
    assert payload["compose_mandate"] is False
    assert payload["instructions"] == "Walk the exact partition."
    return payload


@pytest.mark.parametrize("source", ["member wake", "shared release recipe"])
def test_generated_walk_launch_selects_only_the_derived_level(source):
    if source == "member wake":
        body = stage_wait_message(
            run_id="run-20261125-024",
            stage_name="item-qa",
            item_ref="YOK-5731",
            target_tier="persistent",
            revision="a" * 40,
            reasons="waiting for a fresh walk",
            route=HOLDER,
            names_cases=True,
        )
        match = re.search(r"'(yoke session-control launch create [^']+)'", body)
        assert match
        command = match[1]
        expected_key = "qa-walk:YOK-5731:item-qa:KEY:1"
    else:
        recipe = partition_launch_recipe(
            project="yoke", subject="run-20261125-024:item-qa:smoke",
            leg="-", key="mac", command="yoke qa plan run --partition mac",
        )
        command = recipe.split(" | ", 1)[1]
        expected_key = "qa-walk:run-20261125-024:item-qa:smoke:-:mac:1"

    payload = _parse_launch(_launch_args(command.replace("--level LEVEL", "--level SENIOR")))
    assert payload["level"] == "SENIOR"
    assert payload["idempotency_key"] == expected_key
    assert "executor_surface" not in payload
    assert "model" not in payload


def test_pinning_a_walk_surface_uses_its_model_and_optional_effort():
    recipe = partition_launch_recipe(
        project="yoke", subject="smoke", leg="-", key="mac", command="walk",
    )
    command = recipe.split(" | ", 1)[1].replace(
        "--level LEVEL", "--surface codex-cli --model gpt-6.2-sol --reasoning-effort medium",
    )
    payload = _parse_launch(_launch_args(command))
    assert payload["executor_surface"] == "codex-cli"
    assert payload["model"] == "gpt-6.2-sol"
    assert payload["reasoning_effort"] == "medium"
    assert "level" not in payload
