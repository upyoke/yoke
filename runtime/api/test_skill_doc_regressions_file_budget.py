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
        assert "implementation-bearing intake" in text or "implementation-bearing" in text
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

    def test_review_rubric_covers_issue_and_epic_paths(self, docs):
        text = _read(docs["review_rubric"])
        assert "Issue idea refinement" in text
        assert "Epic plan refinement" in text

    def test_update_protocol_has_file_budget_escalation(self, docs):
        text = _read(docs["update_protocol"])
        assert "File Budget escalation" in text
        # Escalation keeps the item at refining-idea / refining-plan.
        assert "refining-idea" in text
        assert "refining-plan" in text

    def test_skill_md_points_to_rubric_and_escalation(self, docs):
        text = _read(docs["skill"])
        assert "File Budget" in text
        # The pointer must mention escalation routing.
        assert "File Budget escalation" in text or "escalation" in text


class TestFileBudgetAdvanceImplementation:
    """`/yoke advance ... implementation` surfaces File Budget to implementor."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "implementation": SKILLS / "advance" / "implementing" / "implementation.md",
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
            "dispatch_context_gates": SKILLS
            / "conduct"
            / "dispatch-context-gates.md",
            "engineer_tester_dispatch": SKILLS / "conduct" / "engineer-tester-dispatch.md",
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
            "hard_constraints": REPO / "runtime" / "agents" / "architect" / "hard-constraints.md",
        }

    def test_hard_constraints_extends_350_with_file_budget(self, docs):
        text = _read(docs["hard_constraints"])
        # Constraint #15 (file size) stays.
        assert "350" in text
        # Constraint #16 (or later) is the upstream File Budget contract.
        assert "File Budget" in text
        assert "upstream" in text.lower()
        # The contract requires named files and single responsibilities.
        assert "single responsibility" in text.lower() or "single responsibilities" in text.lower()

    def test_hard_constraints_warns_about_oversized_module_responsibilities(self, docs):
        text = _read(docs["hard_constraints"])
        assert "300" in text  # design target visible in plan-time guidance
        # The architect must split before implementation, not after.
        assert "BEFORE planning concludes" in text or "before implementation" in text.lower()

    def test_architect_md_points_to_constraint(self, docs):
        text = _read(docs["architect"])
        assert "File Budget" in text


class TestRefineRecoverableReadinessRepair:
    """`/yoke refine` distinguishes recoverable claim-coverage readiness
    failures from unrecoverable ones, and routes the recoverable ones to
    canonical claim widen / `path-claims narrow` rather than releasing
    the work claim and exiting. Adjacent gates (idea-time readiness,
    advance-time spec coverage, pre-edit/pre-bash path-claim guards) are
    classified as `auto-repair`, `repair-before-block`, or
    `block-by-design` with rationale.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "refine_skill": SKILLS / "refine" / "SKILL.md",
            "refine_readiness_repair": SKILLS / "refine" / "readiness-repair.md",
            "idea_body_and_sync": SKILLS / "idea" / "body-and-sync.md",
            "advance_preflight_checks": SKILLS / "advance" / "preflight-checks.md",
            "do_loop_routing": SKILLS / "do" / "loop-routing.md",
        }

    def test_refine_classifies_recoverable_readiness_codes(self, docs):
        skill = _read(docs["refine_skill"])
        repair = _read(docs["refine_readiness_repair"])
        # The handler names both recoverable codes and the unrecoverable
        # bucket so future readers cannot collapse them back into one class.
        # SKILL.md owns the dispatch; readiness-repair.md owns the table.
        combined = skill + repair
        assert "FILE_BUDGET_NOT_IN_CLAIM" in combined
        assert "CLAIM_NOT_IN_FILE_BUDGET" in combined
        assert "unrecoverable" in combined
        assert "recoverable" in combined

    def test_refine_routes_recoverable_to_canonical_claims_widen(self, docs):
        text = _read(docs["refine_skill"])
        # The repair is canonical `yoke claims path widen` and preserves
        # path_claim_amendments, dispatched via the wrapped readiness command.
        assert "yoke claims path widen" in text
        assert "yoke readiness repair-claim-coverage" in text
        assert "--claim-id" in text
        assert "--add-paths" in text
        assert "--reason" in text
        assert "--item YOK-N" in text
        # Step 4b's narrow remediation must name the explicit keep/drop
        # flag pair, not the bare `--paths` form. `--keep-paths` is the
        # safe default for File Budget reconciliation; `--drop-paths`
        # remains documented for explicit removal.
        assert "path-claims narrow" in text
        assert "--keep-paths" in text
        assert "--drop-paths" in text
        # Anti-regression: the legacy phrasing that taught operators to
        # put kept paths into a drop flag must not return.
        assert "narrow <id> --paths <kept>" not in text
        assert "narrow <id> --paths <" not in text

    def test_idea_body_and_sync_names_explicit_narrow_flags(self, docs):
        text = _read(docs["idea_body_and_sync"])
        # Idea body-and-sync's recoverable-readiness guidance must point
        # operators at the explicit flag pair so the convention is taught
        # at the first place readers learn it.
        assert "path-claims narrow --keep-paths" in text
        # Anti-regression: the bare `path-claims narrow` reference (no
        # flag) should no longer appear in this file's recoverable
        # guidance — operators learn the explicit flags first.
        assert "narrow <id> --paths <" not in text

    def test_refine_does_not_unconditionally_release_on_readiness(self, docs):
        text = _read(docs["refine_skill"])
        # Anti-regression for the original bug: a bare
        # `if [ "$?" -ne 0 ]; then ... release-work-claim ... exit 1`
        # block with no classification is exactly the contradiction this
        # ticket exists to delete.
        assert 'readiness-check-blocked' in text
        # The release/exit must be conditional on the unrecoverable case.
        assert 'unrecoverable' in text
        # The mixed-recoverable path must NOT release; it falls through.
        assert "recoverable-mixed" in text or "continuing into refine" in text

    def test_refine_routes_pure_stale_count_to_repair_helper(self, docs):
        # refine entry distinguishes STALE_LINE_COUNT from
        # terminal failures and dispatches to the auto-repair helper
        # before releasing the claim.
        skill = _read(docs["refine_skill"])
        repair = _read(docs["refine_readiness_repair"])
        assert "pure_stale_count" in skill
        assert "yoke readiness repair-stale-count" in skill
        assert "STALE_LINE_COUNT" in repair
        assert "classify_readiness_issues" in repair
        # The phase doc must explain why the helper exists (chain step
        # contract) — that is the operator-facing rationale.
        assert "chain step" in repair.lower()

    def test_do_loop_routing_treats_repair_as_handler_continuation(self, docs):
        # /yoke do prose teaches that successful
        # refine-entry metadata repair is continuation of the same routed
        # handler — no work-claim release, no chain step consumption for
        # the repair.
        text = _read(docs["do_loop_routing"])
        assert "idea_readiness_repair" in text
        assert "readiness-repair" in text
        # The chain semantics must be explicit, not implied.
        assert "claim stays held" in text or "no separate chain step" in text

    def test_idea_readiness_classifies_as_repair_before_block(self, docs):
        text = _read(docs["idea_body_and_sync"])
        assert "repair-before-block" in text
        # Idea-time check stays advisory; refine is the mandatory pass.
        assert "advisory" in text or "advisory" in text.lower()

    def test_advance_spec_coverage_gate_classifies_as_block_by_design(self, docs):
        text = _read(docs["advance_preflight_checks"])
        assert "block-by-design" in text
        # The rationale must name the worktree timing problem.
        assert "worktree" in text.lower()
        # The sanctioned remediation must point back to refine or
        # canonical claim widen — not invent a new mutation surface.
        assert "/yoke refine" in text or "yoke claims path widen" in text

    def test_pre_edit_and_pre_bash_guards_already_emit_widen_remediation(self):
        """Pre-edit and pre-bash guard narratives teach canonical widen."""
        from yoke_core.domain import path_claim_bash_guard, path_claim_pre_edit_guard

        pre_edit = _read(Path(path_claim_pre_edit_guard.__file__).resolve())
        pre_bash = _read(Path(path_claim_bash_guard.__file__).resolve())
        assert "yoke claims path widen" in pre_edit
        assert "yoke claims path widen" in pre_bash

    def test_idea_body_and_sync_teaches_structured_field_function_adapter(self):
        """task 015: idea body-and-sync teaches the typed function-
        call adapter for structured-field writes, not raw-recipe shell
        choreography. The retained CLI is the function-covered adapter
        ``yoke items structured-field replace --stdin`` (dispatches through
        ``items.structured_field.replace``).
        """
        text = _read(SKILLS / "idea" / "body-and-sync.md")
        assert "yoke items structured-field replace" in text, (
            "idea/body-and-sync.md must teach ``yoke items "
            "structured-field replace --stdin`` "
            "(function id: items.structured_field.replace)."
        )
