"""Doc regressions for the upstream File Budget contract.

The 350-line file rule is enforced by ``yoke_core.domain.file_line_check``
as a late-stage backstop. These tests pin the upstream contract that shapes
the work BEFORE implementation begins:

- `/yoke idea` seeds a `## File Budget` section.
- `/yoke refine` treats missing/vague File Budget as first-class critique
  and escalates unresolved budgets back to the operator.
- The architect plan, advance re-anchor, and conduct Engineer dispatch
  surface the budget to the implementor.
- Engineer submissions carry `file_budget: PASS|SKIP`; conduct re-dispatches
  on missing/malformed/FAIL/UNKNOWN.
- Tester guidance positions `yoke_core.domain.file_line_check` as backup verification.
- The existing late-stage 350-line prose stays intact — the contract is
  purely additive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
)


class TestFileBudgetIdeaSeeding:
    """`/yoke idea` seeds a `## File Budget` section in new bodies."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "skill": SKILLS / "idea" / "SKILL.md",
            "body_and_sync": SKILLS / "idea" / "body-and-sync.md",
        }

    def test_body_and_sync_seeds_file_budget_section(self, docs):
        text = _read(docs["body_and_sync"])
        assert "## File Budget" in text
        assert "350" in text
        assert "300" in text  # design target
        assert "yoke_core.domain.file_line_check" in text

    def test_body_and_sync_handles_three_shapes(self, docs):
        text = _read(docs["body_and_sync"])
        # Implementation-bearing with known shape names example files.
        assert "Expected implementation shape" in text
        # Unknown shape forces refine to resolve.
        assert "UNRESOLVED" in text
        assert "/yoke refine" in text
        # Non-code shape uses N/A with reason.
        assert "N/A" in text

    def test_body_and_sync_minimal_body_includes_file_budget(self, docs):
        text = _read(docs["body_and_sync"])
        # Title-only intake fallback must still mention File Budget.
        assert (
            "implementation-bearing intake" in text or "implementation-bearing" in text
        )
        # The minimal-body section explicitly covers File Budget.
        idx = text.find("If the user provided no body content")
        assert idx >= 0
        tail = text[idx:]
        assert "File Budget" in tail

    def test_skill_md_references_file_budget(self, docs):
        text = _read(docs["skill"])
        assert "File Budget" in text


class TestFileBudgetRefineRubric:
    """`/yoke refine` treats File Budget as a first-class readiness check."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "skill": SKILLS / "refine" / "SKILL.md",
            "critique_pointer": SKILLS / "refine" / "survey-and-focus.md",
            "review_rubric": SKILLS / "refine" / "review-rubric.md",
            "update_protocol": SKILLS / "refine" / "update-protocol.md",
        }

    def test_review_rubric_has_file_budget_dimension(self, docs):
        text = _read(docs["review_rubric"])
        assert "File Budget" in text
        assert "first-class" in text.lower()
        # Rubric mentions both 350 hard limit and 300 design target.
        assert "350" in text
        assert "300" in text

    def test_review_rubric_covers_served_artifact_scopes(self, docs):
        text = _read(docs["review_rubric"])
        assert "Item-artifact refinement" in text
        assert "Generated-task-plan refinement" in text

    def test_update_protocol_keeps_escalation_at_the_served_stage(self, docs):
        text = _read(docs["update_protocol"])
        assert "File Budget escalation" in text
        assert "REFINE_ACTIVE_STATUS" in text
        assert "do not reconstruct them from a workflow name" in text

    def test_skill_md_points_to_rubric_and_escalation(self, docs):
        text = _read(docs["skill"]) + _read(docs["critique_pointer"])
        assert "File Budget" in text
        # The pointer must mention escalation routing.
        assert "File Budget escalation" in text or "escalation" in text


class TestFileBudgetAdvanceImplementation:
    """`/yoke implement` surfaces File Budget to implementor."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "implementation": SKILLS
            / "implement"
            / "implementing"
            / "implementation.md",
        }

    def test_re_anchor_reads_file_budget_section(self, docs):
        text = _read(docs["implementation"])
        # Re-anchor block must instruct the implementor to read File Budget.
        idx = text.find("Implementation Re-Anchor")
        assert idx >= 0
        re_anchor = text[idx:]
        assert "File Budget" in re_anchor
        assert "350" in re_anchor
        assert "300" in re_anchor

    def test_re_anchor_names_canonical_backstop(self, docs):
        text = _read(docs["implementation"])
        idx = text.find("Implementation Re-Anchor")
        re_anchor = text[idx:]
        assert "yoke_core.domain.file_line_check" in re_anchor


class TestFileBudgetConductDispatch:
    """`/yoke conduct` Engineer dispatch carries the File Budget contract."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "dispatch_context_gates": SKILLS / "conduct" / "dispatch-context-gates.md",
            "engineer_tester_dispatch": SKILLS
            / "conduct"
            / "engineer-tester-dispatch.md",
        }

    def test_engineer_dispatch_packet_mentions_file_budget(self, docs):
        text = _read(docs["engineer_tester_dispatch"])
        assert "FILE BUDGET" in text or "File Budget" in text
        assert "350" in text
        # Dispatch packet must reference the canonical backstop.
        assert "yoke_core.domain.file_line_check" in text

    def test_submission_gate_requires_file_budget_key(self, docs):
        text = _read(docs["engineer_tester_dispatch"])
        # Submission gate must list `file_budget` among the required keys.
        assert "`file_budget`" in text or "file_budget" in text
        # And explicitly call out PASS/SKIP semantics.
        assert "file_budget: PASS" in text or "`file_budget`" in text

    def test_post_return_gate_requires_file_budget_key(self, docs):
        text = _read(docs["dispatch_context_gates"])
        assert "file_budget" in text
        assert "PASS" in text and "SKIP" in text
        assert "FAIL" in text and "UNKNOWN" in text

    def test_submission_gate_redispatches_on_failure(self, docs):
        text = _read(docs["engineer_tester_dispatch"])
        # Missing/malformed/FAIL/UNKNOWN must trigger re-dispatch.
        assert "FAIL" in text and "UNKNOWN" in text


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
