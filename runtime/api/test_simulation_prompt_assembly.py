"""Skill-prompt-assembly tests for simulator dispatch.

Owns the contract: assembled retry-tier prompts must contain the epic
ID verbatim in the common contract applied to each mode, and empty
``_epic_ref`` must halt before any dispatch invocation. Native persistence
validates the leading headers and returns named identity errors; these tests
pin the corresponding teaching and exact-item recovery.

Sibling justification: ``test_skill_doc_regressions_conduct_simulation.py``
keeps the broader conduct skill-doc regression coverage focused on
persistence wiring, retry-tier doc structure, and gap-handoff branching.
This sibling file is scoped to prompt-assembly invariants only — making the
contract independently visible and easy to extend when new dispatch
templates land.
"""

from __future__ import annotations

import re

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
        assert 'if [ -z "${_epic_ref:-}" ]; then' in criteria_text

    def test_bail_message_is_critical(self, criteria_text: str):
        assert "[CRITICAL] _epic_ref lost between dispatches" in criteria_text

    def test_bail_documented_for_initial_and_retry_dispatch(self, criteria_text: str):
        assert "before any simulator invocation" in criteria_text.lower()
        assert "initial dispatch" in criteria_text.lower()
        assert "retry" in criteria_text.lower()

    def test_bail_routes_to_cleanup_report_halted(self, criteria_text: str):
        bail_block_start = criteria_text.find('if [ -z "${_epic_ref:-}" ]; then')
        assert bail_block_start >= 0
        # Look at the surrounding paragraph for the routing instruction.
        nearby = criteria_text[max(0, bail_block_start - 400) : bail_block_start + 800]
        assert (
            "cleanup-report.md" in nearby
            and "HALTED" in nearby
            or "halts before any simulator invocation" in nearby
        )

    def test_bail_appears_before_first_dispatch_block(self, criteria_text: str):
        bail_idx = criteria_text.find('if [ -z "${_epic_ref:-}" ]; then')
        assert bail_idx >= 0
        assert "before any simulator invocation" in criteria_text.lower()
        mode_idx = criteria_text.find("## Mode and evidence")
        retry_idx = criteria_text.find("## Parse and bounded output retry")
        assert bail_idx < mode_idx < retry_idx
        assert "Reread the identity check before each invocation" in criteria_text


# ---------------------------------------------------------------------------
# TestRetryPromptsCarryEpicIdVerbatim
# ---------------------------------------------------------------------------


class TestRetryPromptsCarryEpicIdVerbatim:
    """Each retry tier must template the epic ID into the verdict block."""

    def test_formatting_omission_retry_carries_epic_placeholder(
        self, criteria_text: str
    ):
        # Match the documented retry-tier instruction
        assert "EPIC: ${_epic_ref}" in criteria_text
        # And the formatting-omission section names the requirement
        assert (
            "Formatting retry explicitly demands SIMULATION: then EPIC: ${_epic_ref} first"
            in criteria_text
        )

    def test_aggressive_retry_carries_epic_placeholder(self, criteria_text: str):
        # The aggressive retry tier instruction is explicit
        assert (
            "Compressed aggressive retry repeats SIMULATION: then EPIC: ${_epic_ref}"
            in criteria_text
        )

    def test_ultra_compressed_no_tool_fallback_carries_epic_placeholder(
        self, criteria_text: str
    ):
        # The fallback section requires the same two-line block
        assert "Retry2's no-tool" in criteria_text
        assert (
            "prompt likewise repeats SIMULATION: then EPIC: ${_epic_ref}"
            in criteria_text
        )

    def test_dispatch_templates_use_public_ref_placeholder(
        self, dispatch_prompts_text: str
    ):
        # Dispatch templates carry the complete public ref.
        common = dispatch_prompts_text.split("## Common contract", 1)[1].split(
            "## Plan mode", 1
        )[0]
        assert re.search(r"EPIC: \{public_ref\}", common)
        for heading in (
            "## Plan mode",
            "## Standard integration mode",
            "## Compressed integration mode",
        ):
            mode = dispatch_prompts_text.split(heading, 1)[1].split("\n## ", 1)[0]
            assert "common contract" in mode.lower(), heading

    def test_retry_placeholder_count_at_least_three(self, criteria_text: str):
        # Three retry tiers (formatting-omission, aggressive, ultra-compressed)
        assert criteria_text.count("EPIC: ${_epic_ref}") >= 3


# ---------------------------------------------------------------------------
# TestCompressedContextCommitBoundaryEvidence
# ---------------------------------------------------------------------------


class TestCompressedContextCommitBoundaryEvidence:
    """Compressed prompts must surface parent-supplied commit evidence."""

    def test_dispatch_prompt_has_commit_boundary_section(
        self, dispatch_prompts_text: str
    ):
        normalized = " ".join(dispatch_prompts_text.split())
        assert "Commit-Boundary Evidence:" in normalized
        assert "parent-supplied git log --oneline -- path" in normalized
        assert "commit evidence unavailable: no affected file named" in normalized

    def test_dispatch_prompt_keeps_simulator_git_archaeology_forbidden(
        self, dispatch_prompts_text: str
    ):
        assert "parent-supplied" in dispatch_prompts_text
        assert "do not run" in dispatch_prompts_text
        assert "git log/blame unless explicitly requested" in dispatch_prompts_text

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
        assert "Shim exports:" in dispatch_prompts_text
        assert "public and private names such as _BLOCKS" in dispatch_prompts_text
        assert "shim import list is the source of truth" in dispatch_prompts_text

    def test_conduct_compressed_context_includes_private_shim_exports(
        self, criteria_text: str
    ):
        normalized = " ".join(criteria_text.split())
        assert "Shim Re-Export Contracts" in normalized
        assert "underscore-prefixed re-export such as _BLOCKS" in normalized
        assert "source import list is the source of truth" in normalized


# ---------------------------------------------------------------------------
# TestExitCodeContractSurfacedToOperator
# ---------------------------------------------------------------------------


class TestIdentityDiagnosticContract:
    """Native persistence errors retain identity and exact-header recovery."""

    def test_wrong_item_diagnostic(self, criteria_text: str):
        assert "simulation_identity_mismatch" in criteria_text
        assert "wrong-epic body" in criteria_text

    def test_missing_identity_diagnostic(self, criteria_text: str):
        assert "simulation_identity_missing" in criteria_text
        assert "absent leading headers" in criteria_text

    def test_diagnostic_retains_intended_and_attested_refs(self, criteria_text: str):
        assert "intended ref and report's attested ref" in criteria_text

    def test_recovery_requires_the_intended_items_headers(self, criteria_text: str):
        assert (
            "SIMULATION and EPIC headers for the exact intended item" in criteria_text
        )

    def test_dispatch_prompts_warn_about_persistence_rejection(
        self, dispatch_prompts_text: str
    ):
        common = dispatch_prompts_text.split("## Common contract", 1)[1].split(
            "## Plan mode", 1
        )[0]
        assert "simulation_identity_missing" in common
        assert "simulation_identity_mismatch" in common
