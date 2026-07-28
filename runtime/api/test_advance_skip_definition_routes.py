"""Pinned-definition route and allowlist coverage for advance skips."""

from __future__ import annotations

import io
from copy import deepcopy
from dataclasses import replace

import pytest

from yoke_core.domain import advance_skip_core
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def test_polish_route_includes_new_stages_from_the_pinned_definition():
    workflow = builtin_workflow_runtime("issue")
    definition = deepcopy(workflow.definition)
    implemented_index = next(
        index
        for index, stage in enumerate(definition["stages"])
        if stage["id"] == "implemented"
    )
    definition["stages"].insert(
        implemented_index,
        {"id": "stabilizing", "label": "stabilizing", "gates": []},
    )
    definition["transitions"] = [
        transition
        for transition in definition["transitions"]
        if transition
        != {
            "from_stage_id": "polishing-implementation",
            "to_stage_id": "implemented",
        }
    ]
    definition["transitions"].extend(
        [
            {
                "from_stage_id": "polishing-implementation",
                "to_stage_id": "stabilizing",
            },
            {
                "from_stage_id": "stabilizing",
                "to_stage_id": "implemented",
            },
        ]
    )
    pinned = replace(workflow, definition=definition)

    route = advance_skip_core._executor_skip_route(
        pinned,
        "reviewed-implementation",
        executor_id="polish",
        require_entry=True,
    )

    assert route.hops == (
        "polishing-implementation",
        "stabilizing",
        "implemented",
    )


def test_polish_allowlist_excludes_pre_implementation_stages():
    workflows = tuple(map(builtin_workflow_runtime, ("issue", "epic")))
    pre_implementation = {
        stage
        for workflow in workflows
        for stage in workflow.stage_ids
        if workflow.is_before_implementation(stage)
    }
    allowed_hops = {
        stage
        for workflow in workflows
        for stage in advance_skip_core._executor_skip_route(
            workflow,
            "reviewed-implementation",
            executor_id="polish",
            require_entry=True,
        ).allowed_hops
    }

    assert not allowed_hops & pre_implementation


def test_refine_allowlist_comes_from_each_bound_segment():
    issue_route = advance_skip_core._executor_skip_route(
        builtin_workflow_runtime("issue"),
        "idea",
        executor_id="refine",
    )
    epic_plan_route = advance_skip_core._executor_skip_route(
        builtin_workflow_runtime("epic"),
        "plan-drafted",
        executor_id="refine",
    )

    assert issue_route.allowed_hops == frozenset(
        {"refining-idea", "refined-idea"}
    )
    assert epic_plan_route.allowed_hops == frozenset(
        {"refining-plan", "planned"}
    )


def test_walk_hops_rejects_out_of_route_allowlist():
    route = advance_skip_core._executor_skip_route(
        builtin_workflow_runtime("issue"),
        "reviewed-implementation",
        executor_id="polish",
        require_entry=True,
    )

    with pytest.raises(ValueError, match="not in allowlist"):
        advance_skip_core._walk_hops(
            1,
            hops=["implementing"],
            bypass_reason="skip-polish",
            allowlist=route.allowed_hops,
            out=io.StringIO(),
        )
