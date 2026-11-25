"""Release notices and refusals print commands accepted by the real run parser."""

import re
import shlex
from unittest.mock import patch

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    RUN,
    SLUG,
    MEMBERS,
    _seed,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_plan_group_dispatch import _group_lines
from yoke_core.domain.deployment_qa_plan_credit import _miss
from yoke_core.domain.deployment_qa_failure_handoff import retry_command_for_stage
from yoke_core.domain.deployment_qa_shared_execution import _begin_open_group
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    execution_target_for_roster,
)
from yoke_core.domain import qa_plan_execution_cli, qa_plan_partitions_cli


def test_printed_release_recipes_parse(test_db):
    plan = _seed(test_db, attached=MEMBERS[:2])
    ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    (group,) = run_groups(test_db, RUN)
    recipes = _group_lines(test_db, RUN, "item-qa", [group], str)
    miss = _miss(
        MEMBERS[0], plan, SLUG, {"id": RUN}, "item-qa", "stage",
        carried_ids=[], conn=test_db,
    )
    recipes.append(miss["recovery"])
    recipes += [retry_command_for_stage(test_db, run_id=RUN, stage="item-qa",
        member_ref=None, member_id=None, project=None, plan=SLUG)]
    assert retry_command_for_stage(
        test_db, run_id=RUN, stage="item-qa", member_ref=None, member_id=None, project=None,
    ) == f"yoke deployment runs get {RUN}"
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
    with pytest.raises(ValueError) as mixed:
        execution_target_for_roster([
            {"execution_target": {"target": value}, "execution_target_digest": value}
            for value in ("one", "two")])
    assert "`yoke qa plan partitions`" in str(mixed.value)
    assert len(recipes) == 5
    for recipe in recipes:
        tokens = shlex.split(recipe, comments=True)
        if tokens[1] == "--env":
            del tokens[1:3]
        assert tokens[:3] == ["yoke", "qa", "plan"], recipe
        args = tokens[4:]
        if tokens[3] == "partitions":
            with patch.object(qa_plan_partitions_cli, "call_plan_function", return_value={"partitions": []}), patch(
                "yoke_contracts.runtime_ports.structured_dispatch.get_structured_dispatch"
            ):
                assert qa_plan_partitions_cli.run(args) == 0, recipe
        else:
            assert tokens[3] == "run", recipe
            with patch.object(qa_plan_execution_cli, "execute_plan", return_value={"state": "passed", "results": []}):
                assert qa_plan_execution_cli.run(args) == 0, recipe
