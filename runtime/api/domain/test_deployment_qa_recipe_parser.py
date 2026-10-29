"""Release notices and refusals print commands accepted by the real run parser."""

import re
import shlex
from unittest.mock import patch

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import RUN, SLUG, MEMBERS, _seed
from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run, _stages
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups, group_subject
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_plan_group_dispatch import _group_lines
from yoke_core.domain.deployment_qa_plan_credit import _miss
from yoke_core.domain.deployment_qa_failure_handoff import retry_command_for_stage
from yoke_core.domain.deployment_qa_stage_wake import run_stage_wait_message
from yoke_core.domain.deployment_qa_shared_execution import _begin_open_group
from yoke_core.domain.qa_plan_execution_target_snapshot import execution_target_for_roster
from yoke_core.domain import qa_plan_execution_cli


def test_printed_release_recipes_parse(test_db):
    plan = _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, RUN)
    recipes = _group_lines(test_db, RUN, "item-qa", [group], str)
    recipes += [_miss(MEMBERS[0], plan, SLUG, {"id": RUN}, "item-qa", "stage")["recovery"]]
    recipes += [retry_command_for_stage(test_db, run_id=RUN, stage="item-qa",
        member_ref=None, member_id=None, project=None)]
    with pytest.raises(ValueError) as unattached:
        _begin_open_group(test_db, None, {"plan": SLUG, "deployment_member_item_id": MEMBERS[2]},
                          RUN, "item-qa", {})
    recipes += re.findall(r"`(yoke qa plan run [^`]+)`", str(unattached.value))
    stages = _stages(plan)
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id="run-recipes-shared", stages=stages, members=())
    with pytest.raises(ValueError) as wrong_scope:
        group_subject(test_db, "run-recipes-shared", "item-qa", group, require_active=True)
    recipes += re.findall(r"`(yoke qa plan run [^`]+)`", str(wrong_scope.value))
    notice = run_stage_wait_message(run_id=RUN, stage_name="item-qa", target_tier="persistent",
        revision="a" * 40, reasons="awaiting cases", route="driver", names_cases=False)
    recipes += re.findall(r"'(yoke watch qa-plan -- [^']+)'", notice)
    with pytest.raises(ValueError) as mixed:
        execution_target_for_roster([
            {"execution_target": {"target": value}, "execution_target_digest": value}
            for value in ("one", "two")])
    text = str(mixed.value)
    recipes += [re.search(r"deployment QA stage with (yoke qa plan run .+?), or each", text)[1]]
    assert len(recipes) == 7
    for recipe in recipes:
        tokens = shlex.split(recipe, comments=True)
        args = tokens[4:]
        with patch.object(qa_plan_execution_cli, "execute_plan", return_value={"state": "passed", "results": []}):
            assert qa_plan_execution_cli.run(args) == 0, recipe
