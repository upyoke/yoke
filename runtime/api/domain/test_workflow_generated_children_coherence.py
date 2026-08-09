"""A workflow may only promise decomposition its own skills produce."""

from __future__ import annotations

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    TASK_PRODUCING_PLANNING_SKILL_IDS,
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)


def _bound_skills(definition):
    return {binding["skill_id"] for binding in definition["skill_bindings"]}


def test_generated_children_requires_a_skill_that_produces_tasks():
    """A workflow may not promise decomposition its own skills never write.

    Declaring epic_tasks without binding a task-producing planning skill
    validates today and then populates nothing, and an empty task set reads
    downstream as a finished decomposition rather than an absent one.
    """
    dash = builtin_workflow_definition("dash")["definition"]
    assert not _bound_skills(dash) & TASK_PRODUCING_PLANNING_SKILL_IDS
    dash["policies"]["generated_children"] = "epic_tasks"
    with pytest.raises(WorkflowDefinitionError, match="produces tasks"):
        validate_workflow_definition(dash)


def test_epic_declares_generated_children_and_binds_its_producer():
    epic = builtin_workflow_definition("epic")["definition"]
    assert epic["policies"]["generated_children"] == "epic_tasks"
    assert _bound_skills(epic) & TASK_PRODUCING_PLANNING_SKILL_IDS
    validate_workflow_definition(epic)


def test_generated_children_none_needs_no_planning_skill():
    """The rule constrains the claim, not every workflow: a workflow that
    generates nothing is free of it regardless of which skills it binds."""
    dash = builtin_workflow_definition("dash")["definition"]
    assert dash["policies"]["generated_children"] == "none"
    validate_workflow_definition(dash)
