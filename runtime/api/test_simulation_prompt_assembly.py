"""Skill-prompt-assembly tests for simulator dispatch.

Owns the contract: every Simulator prompt and retry carries the public epic
ref in its leading headers, and an empty ``_epic_ref`` halts before any
dispatch. Native persistence validates those headers and refuses with named
identity errors, so these tests pin only the teaching that feeds it.

Sibling justification: ``test_skill_doc_regressions_conduct_simulation.py``
keeps the broader conduct skill-doc regression coverage focused on
persistence wiring and gap-handoff branching. This sibling file is scoped to
prompt-assembly invariants only.
"""

from __future__ import annotations

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


@pytest.fixture
def criteria_text() -> str:
    return _read(SKILLS / "conduct" / "simulation-gate-criteria.md")


@pytest.fixture
def dispatch_prompts_text() -> str:
    return " ".join(_read(SKILLS / "simulate" / "dispatch-prompts.md").split())


class TestEmptyEpicIdHaltsBeforeDispatch:
    """The defensive bail must fire BEFORE any simulator dispatch call."""

    def test_bail_precedes_dispatch_and_persistence(self, criteria_text: str):
        bail = criteria_text.find("Empty _epic_ref halts first")
        assert bail >= 0
        assert bail < criteria_text.find("simulation-upsert")


class TestPromptsCarryEpicIdVerbatim:
    """Each dispatch and retry tier keeps the epic ref in its headers."""

    def test_dispatch_template_uses_public_ref_placeholder(
        self, dispatch_prompts_text: str
    ):
        assert (
            "Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, "
            "then EPIC: {public_ref}." in dispatch_prompts_text
        )

    def test_conduct_dispatch_requires_epic_header(self, criteria_text: str):
        assert "then `EPIC: PREFIX-N`" in criteria_text

    def test_retries_keep_headers_and_never_synthesize_clean(self):
        retry = " ".join(_read(SKILLS / "conduct" / "retry-budgets.md").split())
        assert "retry 1 demands the two header lines" in retry
        assert "retry 2 allows no tools and at most 3 gaps" in retry
        assert "never write CLEAN yourself" in retry


class TestCompressedContextEvidence:
    """Compressed prompts carry parent-supplied shim and commit evidence."""

    def test_dispatch_prompt_carries_shim_exports_and_commit_evidence(
        self, dispatch_prompts_text: str
    ):
        assert "private names included, from the shim import list" in (
            dispatch_prompts_text
        )
        assert "parent-supplied `git log --oneline -- {file}`" in (
            dispatch_prompts_text
        )

    def test_simulator_role_forbids_git_archaeology(self):
        role = " ".join(_read(REPO / "runtime/agents/simulator.md").split())
        assert "log/blame unless asked" in role
