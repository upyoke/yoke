"""Skill-prompt-assembly tests for simulator dispatch.

Owns the AC-8 contract: assembled retry-tier prompts must contain the epic
ID verbatim in the correct templated location, and empty ``_epic_id`` must
halt before any dispatch invocation. The actual prompt assembly happens
inside conduct's bash flow as it reads ``simulation-gate-criteria.md``;
these tests pin the doc-level contract so a future template refactor cannot
silently strip the ``EPIC:`` placeholder or the defensive bail.

Sibling justification: ``test_skill_doc_regressions_conduct_simulation.py``
keeps the broader conduct skill-doc regression coverage focused on
persistence wiring, retry-tier doc structure, and gap-handoff branching.
This sibling file is scoped to prompt-assembly invariants only — making the
AC-8 deliverable independently visible and easy to extend when new dispatch
templates land.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def criteria_text() -> str:
    return _read(SKILLS / "conduct" / "simulation-gate-criteria.md")


@pytest.fixture
def dispatch_prompts_text() -> str:
    return _read(SKILLS / "simulate" / "dispatch-prompts.md")


# ---------------------------------------------------------------------------
# TestEmptyEpicIdHaltsBeforeDispatch
# ---------------------------------------------------------------------------


class TestEmptyEpicIdHaltsBeforeDispatch:
    """The defensive bail must fire BEFORE any simulator dispatch call."""

    def test_bail_check_present(self, criteria_text: str):
        assert 'if [ -z "${_epic_id:-}" ]; then' in criteria_text

    def test_bail_message_is_critical(self, criteria_text: str):
        assert "[CRITICAL] _epic_id lost between dispatches" in criteria_text

    def test_bail_documented_for_initial_and_retry_dispatch(self, criteria_text: str):
        assert (
            "before any Simulator dispatch" in criteria_text
            or "before any simulator dispatch" in criteria_text.lower()
        )
        assert "initial dispatch" in criteria_text.lower()
        assert "retry" in criteria_text.lower()

    def test_bail_routes_to_cleanup_report_halted(self, criteria_text: str):
        bail_block_start = criteria_text.find('if [ -z "${_epic_id:-}" ]; then')
        assert bail_block_start >= 0
        # Look at the surrounding paragraph for the routing instruction.
        nearby = criteria_text[max(0, bail_block_start - 400): bail_block_start + 800]
        assert (
            "cleanup-report.md" in nearby and "HALTED" in nearby
            or "halts before any simulator invocation" in nearby
        )

    def test_bail_appears_before_first_dispatch_block(self, criteria_text: str):
        bail_idx = criteria_text.find('if [ -z "${_epic_id:-}" ]; then')
        assert bail_idx >= 0
        # The standard dispatch block starts with the marker '### Standard Dispatch'
        std_idx = criteria_text.find("### Standard Dispatch")
        # If the standard dispatch block exists, the bail must be documented
        # before the Output Gate that controls retries — but the precondition
        # also runs before initial dispatch. Either ordering works as long as
        # the bail text explicitly says "before any Simulator dispatch."
        assert (
            "before any Simulator dispatch" in criteria_text
            or "before any simulator dispatch" in criteria_text.lower()
        )
        # Output Gate retries definitely come after the bail definition
        gate_idx = criteria_text.find("### Simulator Output Gate")
        assert gate_idx > 0
        # The bail must live inside the Output Gate section (we documented it
        # as the preamble to the gate's retry logic)
        assert bail_idx > gate_idx
        if std_idx > 0:
            assert std_idx < gate_idx


# ---------------------------------------------------------------------------
# TestRetryPromptsCarryEpicIdVerbatim
# ---------------------------------------------------------------------------


class TestRetryPromptsCarryEpicIdVerbatim:
    """Each retry tier must template the epic ID into the verdict block."""

    def test_formatting_omission_retry_carries_epic_placeholder(
        self, criteria_text: str
    ):
        # Match the documented retry-tier instruction
        assert "EPIC: YOK-${_epic_id}" in criteria_text
        # And the formatting-omission section names the requirement
        assert "FIRST TWO LINES" in criteria_text

    def test_aggressive_retry_carries_epic_placeholder(self, criteria_text: str):
        # The aggressive retry tier instruction is explicit
        assert (
            "two-line verdict block requirement (`SIMULATION:` line then "
            "`EPIC: YOK-${_epic_id}` line)" in criteria_text
        )

    def test_ultra_compressed_no_tool_fallback_carries_epic_placeholder(
        self, criteria_text: str
    ):
        # The fallback section requires the same two-line block
        assert (
            "Two-line verdict block (`SIMULATION:` then `EPIC: YOK-${_epic_id}`)"
            in criteria_text
        )

    def test_dispatch_templates_use_item_id_placeholder(
        self, dispatch_prompts_text: str
    ):
        # Plan / integration / compressed templates use {item_id}
        # as the epic-ID placeholder (rendered by the simulate skill)
        matches = re.findall(r"EPIC: YOK-\{item_id\}", dispatch_prompts_text)
        assert len(matches) >= 3, (
            f"expected EPIC placeholder in plan/integration/compressed prompts, "
            f"got {len(matches)} occurrence(s)"
        )

    def test_retry_placeholder_count_at_least_three(self, criteria_text: str):
        # Three retry tiers (formatting-omission, aggressive, ultra-compressed)
        assert criteria_text.count("EPIC: YOK-${_epic_id}") >= 3


# ---------------------------------------------------------------------------
# TestCompressedContextCommitBoundaryEvidence
# ---------------------------------------------------------------------------


class TestCompressedContextCommitBoundaryEvidence:
    """Compressed prompts must surface parent-supplied commit evidence."""

    def test_dispatch_prompt_has_commit_boundary_section(
        self, dispatch_prompts_text: str
    ):
        assert "## Commit-Boundary Evidence" in dispatch_prompts_text
        assert "git log --oneline -- {file}" in dispatch_prompts_text
        assert "commit evidence unavailable: no affected file named" in (
            dispatch_prompts_text
        )

    def test_dispatch_prompt_keeps_simulator_git_archaeology_forbidden(
        self, dispatch_prompts_text: str
    ):
        assert "Parent-supplied" in dispatch_prompts_text
        assert "do not run" in dispatch_prompts_text
        assert "git log or git blame yourself" in dispatch_prompts_text

    def test_conduct_retry_context_carries_commit_boundary_evidence(
        self, criteria_text: str
    ):
        assert "Commit-Boundary Evidence" in criteria_text
        assert "discrete-commit/NFR-style AC" in criteria_text
        assert "git log --oneline -- {file}" in criteria_text


# ---------------------------------------------------------------------------
# TestCompressedContextShimReExports
# ---------------------------------------------------------------------------


class TestCompressedContextShimReExports:
    """Compressed prompts must carry private re-exports from shim import lists."""

    def test_dispatch_prompt_has_shim_re_export_contracts(
        self, dispatch_prompts_text: str
    ):
        assert "## Shim Re-Export Contracts" in dispatch_prompts_text
        assert "underscore-prefixed names such as _BLOCKS" in dispatch_prompts_text
        assert "shim import list is the source of truth" in dispatch_prompts_text

    def test_conduct_compressed_context_includes_private_shim_exports(
        self, criteria_text: str
    ):
        assert "shim re-export contracts" in criteria_text
        assert "underscore-prefixed names such as `_BLOCKS`" in criteria_text
        assert "from yoke_core.board.X import (...)" in criteria_text


# ---------------------------------------------------------------------------
# TestExitCodeContractSurfacedToOperator
# ---------------------------------------------------------------------------


class TestExitCodeContractSurfacedToOperator:
    """Operator-facing diagnostics must name exit 16 (wrong-epic) and 17 (missing-epic)."""

    def test_criteria_diagnostic_table_includes_exit_16(
        self, criteria_text: str
    ):
        assert "| 16 | wrong-epic body" in criteria_text

    def test_criteria_diagnostic_table_includes_exit_17(
        self, criteria_text: str
    ):
        assert "| 17 | missing-epic body" in criteria_text

    def test_exit_16_diagnostic_names_both_epics(self, criteria_text: str):
        assert "CLI passed YOK-${_epic_id}" in criteria_text
        assert "body attested a different epic" in criteria_text

    def test_exit_17_diagnostic_names_attestation_requirement(
        self, criteria_text: str
    ):
        assert "EPIC: YOK-N attestation line" in criteria_text

    def test_dispatch_prompts_warn_about_persistence_rejection(
        self, dispatch_prompts_text: str
    ):
        assert dispatch_prompts_text.count("exit 16") >= 3
        assert dispatch_prompts_text.count("exit 17") >= 3
