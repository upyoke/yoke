"""Dash skill-doc regression: QA materialization precedes the gate it feeds.

The ``implementing -> reviewing-implementation`` preflight materializes every
attached plan into blocking case rows and only then evaluates that stage's
gates, so a recipe that names the transition before the materialization
teaches an ordering that fails on its own first attempt. These assertions pin
the command name and the ordering into the recipe itself.
"""

from __future__ import annotations

import pytest

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read

MATERIALIZE_COMMAND = "yoke qa plan materialize --item ITEM --transition reviewing-implementation"
TRANSITION_COMMAND = (
    "yoke lifecycle transition ITEM --from implementing --to reviewing-implementation"
)


class TestDashQaMaterializationOrder:
    """The Dash recipe names the materialization command and runs it first."""

    @pytest.fixture
    def dash_doc(self) -> str:
        skill_dir = SKILLS / "dash"
        return "\n".join(
            _read(path) for path in sorted(skill_dir.glob("*.md"))
        )

    def test_names_the_materialization_command(self, dash_doc: str):
        assert MATERIALIZE_COMMAND in dash_doc
        assert "yoke qa requirement list --item ITEM --json" in dash_doc
        assert "yoke qa case run --requirement-id <requirement-id>" in dash_doc

    def test_materializes_before_the_transition_that_gates_on_it(self, dash_doc: str):
        materialize_at = dash_doc.index(MATERIALIZE_COMMAND)
        transition_at = dash_doc.index(TRANSITION_COMMAND)
        assert materialize_at < transition_at, (
            "the materialization command must precede the "
            "implementing -> reviewing-implementation transition it feeds"
        )

    def test_materialization_is_not_conditioned_on_selected_posture(self, dash_doc: str):
        materialize_at = dash_doc.index(MATERIALIZE_COMMAND)
        posture_at = dash_doc.index("Then execute each selected posture knob")
        assert materialize_at < posture_at, (
            "an attached project-default plan materializes regardless of posture, "
            "so the recipe must teach it outside the posture-conditional list"
        )

    def test_registers_the_qa_operation_authority(self, dash_doc: str):
        assert "`qa.plan.materialize`" in dash_doc
        assert "`qa.requirement.list`" in dash_doc
