"""Rendered member QA recipes parse through the commands they teach."""

from pathlib import Path
import re
import shlex
from unittest.mock import patch

import pytest

from yoke_contracts.deployment_release_roles_teaching import RELEASE_ROLE_RECIPE
from yoke_contracts.machine_qa_case_target import case_target_recovery
from yoke_core.domain import qa_plan_execution_cli
from yoke_core.domain.deployment_run_other_target_members import (
    OwedRequirement,
    set_aside_message,
)
from yoke_cli.commands.adapters.qa_execution_subjects import (
    qa_plan_materialize_for_item,
)


ITEM = "EXAMPLE-7"


def _member_run_recipes():
    recipe = RELEASE_ROLE_RECIPE.replace("\\\n", " ")
    yield re.search(r"yoke watch qa-plan -- --item [^\n]+", recipe).group()
    root = Path(__file__).resolve().parents[3]
    guide = (root / "docs/testing-verification/installer-campaign.md").read_text()
    yield re.search(r"yoke watch qa-plan -- --item [^\n]+", guide).group()
    notice = set_aside_message(
        public_ref=ITEM,
        run_id="example-run",
        environment="prod",
        owed=(OwedRequirement(1, "post_deploy", "stage"),),
        route="steering",
    )
    yield re.search(r"`(yoke qa plan run [^`]+)`", notice).group(1)


@pytest.mark.parametrize("recipe", list(_member_run_recipes()))
def test_taught_member_execution_command_parses(recipe, capsys):
    tokens = shlex.split(recipe)
    args = tokens[tokens.index("--") + 1 :] if "--" in tokens else tokens[4:]
    with patch.object(
        qa_plan_execution_cli, "execute_plan", return_value={"state": "passed"}
    ) as execute:
        assert qa_plan_execution_cli.run(args) == 0
    assert execute.call_args.kwargs["public_ref"] == args[args.index("--item") + 1]
    assert execute.call_args.kwargs["deployment_stage"] == "STAGE"
    assert execute.call_args.kwargs["deployment_run_id"] is None
    capsys.readouterr()


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
