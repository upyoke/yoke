"""Doc regressions for the upstream File Budget contract.

The 350-line file rule is enforced by ``yoke_core.domain.file_line_check``
as a late-stage backstop. These tests pin the upstream contract that shapes
the work BEFORE implementation begins:

- `/yoke idea` seeds a `## File Budget` section.
- `/yoke refine` critiques the File Budget and escalates unresolved scope.
- The architect plan and the Engineer role surface the budget to the
  implementor.
- Engineer submissions carry `file_budget: PASS|SKIP`; conduct re-dispatches
  on any receipt defect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
    _read_bundle,
)


class TestFileBudgetIdeaSeeding:
    """`/yoke idea` seeds a `## File Budget` section in new bodies."""

    def test_spec_step_seeds_file_budget_when_enabled(self):
        text = _read(SKILLS / "idea" / "body-and-sync.md")
        assert "[File Budget](file-budget.md) when enabled" in text

    def test_file_budget_template_covers_three_shapes(self):
        text = _read(SKILLS / "idea" / "file-budget.md")
        assert "## File Budget" in text
        # Unknown shape forces refine to resolve; non-code shape uses N/A.
        assert "UNRESOLVED" in text
        assert "N/A" in text


class TestFileBudgetRefineRubric:
    """`/yoke refine` treats File Budget as a readiness check."""

    def test_review_rubric_has_file_budget_dimension(self):
        text = _read(SKILLS / "refine" / "review-rubric.md")
        assert "File Budget" in text
        assert "300" in text

    def test_workflow_context_names_served_artifact_scopes(self):
        text = _read(SKILLS / "refine" / "workflow-context.md")
        assert "`generated_task_plan`" in text
        assert "`item_artifact`" in text

    def test_update_protocol_escalates_at_the_served_stage(self):
        text = _read(SKILLS / "refine" / "update-protocol.md")
        assert "escalates" in text
        assert "REFINE_ACTIVE_STATUS" in text

    def test_skill_points_to_file_budget_and_escalation(self):
        text = _read_bundle(
            SKILLS / "refine" / "SKILL.md", SKILLS / "refine" / "survey-and-focus.md"
        )
        assert "File Budget" in text
        assert "escalate" in text.lower()


class TestFileBudgetAdvanceImplementation:
    """`/yoke implement` re-anchors on the spec; AGENTS.md owns the limit."""

    def test_re_anchor_reads_spec(self):
        text = _read(SKILLS / "implement" / "implementing" / "implementation.md")
        re_anchor = text[text.index("Implementation Re-Anchor") :]
        assert "yoke items get PREFIX-N spec" in re_anchor

    def test_agents_md_names_canonical_backstop(self):
        text = _read(REPO / "AGENTS.md")
        assert "350-line authored-file limit" in text
        assert "yoke_core.domain.file_line_check" in text


class TestFileBudgetConductDispatch:
    """Engineer submissions carry the File Budget contract conduct gates on."""

    @pytest.fixture
    def engineer(self) -> str:
        return _read(REPO / "runtime" / "agents" / "engineer.md")

    def test_engineer_reads_file_budget_and_canonical_backstop(self, engineer):
        assert "File Budget" in engineer
        assert "350" in engineer
        assert "yoke_core.domain.file_line_check" in engineer

    def test_submission_block_requires_file_budget_key(self, engineer):
        assert "file_budget: PASS | SKIP" in engineer
        assert "Missing/malformed/FAIL/UNKNOWN fields redispatch" in engineer

    def test_submission_gate_redispatches_on_receipt_defect(self):
        text = _read(SKILLS / "conduct" / "dispatch-context-gates.md")
        assert "submission-receipt-get" in text
        assert "re-dispatches Engineer at the SAME attempt" in text


class TestFileBudgetArchitect:
    """Architect's hard constraints carry the upstream File Budget."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "architect": REPO / "runtime" / "agents" / "architect.md",
            "hard_constraints": REPO
            / "runtime"
            / "agents"
            / "architect"
            / "hard-constraints.md",
        }

    def test_hard_constraints_extends_350_with_file_budget(self, docs):
        text = _read(docs["hard_constraints"])
        # Constraint #15 (file size) stays.
        assert "350" in text
        # Constraint #16 (or later) is the upstream File Budget contract.
        assert "File Budget" in text
        assert "upstream" in text.lower()
        # The contract requires named files and single responsibilities.
        assert (
            "single responsibility" in text.lower()
            or "single responsibilities" in text.lower()
        )

    def test_hard_constraints_warns_about_oversized_module_responsibilities(self, docs):
        text = _read(docs["hard_constraints"])
        assert "300" in text  # design target visible in plan-time guidance
        # The architect must split before implementation, not after.
        assert (
            "BEFORE planning concludes" in text
            or "before implementation" in text.lower()
        )

    def test_architect_md_points_to_constraint(self, docs):
        text = _read(docs["architect"])
        assert "File Budget" in text
