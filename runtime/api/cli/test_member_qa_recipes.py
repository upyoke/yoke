"""Rendered member QA recipes parse through the commands they teach."""

from pathlib import Path
import re
import shlex
from unittest.mock import patch

import pytest

from yoke_contracts.deployment_release_roles_teaching import RELEASE_ROLE_RECIPE
from yoke_contracts.machine_qa_case_target import case_target_recovery
from yoke_core.domain import qa_plan_partitions_cli
from yoke_core.domain.deployment_run_other_target_members import (
    OwedRequirement,
    set_aside_message,
)
from yoke_cli.commands.adapters.qa_execution_subjects import (
    qa_plan_materialize_for_item,
)


ITEM = "EXAMPLE-7"


def _member_partition_recipes():
    root = Path(__file__).resolve().parents[3]
    guide = (root / "docs/testing-verification/installer-campaign.md").read_text()
    for source in (RELEASE_ROLE_RECIPE, guide):
        yield re.search(r"yoke qa plan partitions --item [^\n]+", source).group()
    notice = set_aside_message(
        public_ref=ITEM,
        run_id="example-run",
        environment="prod",
        owed=(OwedRequirement(1, "post_deploy", "stage"),),
        route="steering",
    )
    yield re.search(r"`(yoke qa plan partitions [^`]+)`", notice).group(1)


@pytest.mark.parametrize("command", list(_member_partition_recipes()))
def test_taught_member_partition_command_names_the_exact_subject(command):
    with (
        patch("yoke_contracts.runtime_ports.structured_dispatch.get_structured_dispatch"),
        patch.object(
            qa_plan_partitions_cli, "call_plan_function", return_value={"partitions": []}
        ) as call,
    ):
        assert qa_plan_partitions_cli.run(shlex.split(command)[4:]) == 0
    kwargs = call.call_args.kwargs
    assert kwargs["function_id"] == "qa.plan_execution.partitions"
    args = shlex.split(command)
    assert kwargs["target"].public_ref == args[args.index("--item") + 1]
    assert kwargs["payload"]["deployment_stage"] == "STAGE"
    assert kwargs["payload"]["deployment_run_id"] == "RUN"


@pytest.mark.parametrize("member", [ITEM, None])
def test_target_recovery_materialization_command_parses(member):
    recovery = case_target_recovery(
        project="example",
        plan_id=431,
        deployment_run_id="example-run",
        deployment_stage="item-qa",
        deployment_member=member,
    )
    command = re.search(r"`(yoke qa plan materialize [^`]+)`", recovery).group(1)
    with patch(
        "yoke_cli.commands.adapters.qa_execution_subjects.dispatch_and_emit",
        return_value=0,
    ) as dispatch:
        assert qa_plan_materialize_for_item(shlex.split(command)[4:]) == 0
    kwargs = dispatch.call_args.kwargs
    assert kwargs["payload"]["deployment_stage"] == "item-qa"
    assert kwargs["target"].kind == ("item" if member else "deployment_run")
    if member:
        assert kwargs["target"].public_ref == member
    else:
        assert kwargs["target"].deployment_run_id == "example-run"
