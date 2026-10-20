"""Path-claim teaching preserves scope and requires its operation reference."""

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


class TestNoDescopeForActivePathClaims:
    """Active path claims must not narrow work-item scope.

    A work item's correct implementation scope must never be narrowed,
    descoped, or rewritten solely because a required path is already
    claimed. Active path claims are coordination/dependency/blocking
    facts about who currently coordinates work on a path — never
    permission to omit a required file from a work item.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        idea = SKILLS / "idea"
        return {
            "agents": REPO / "AGENTS.md",
            "claims_reference": REPO / ".yoke/docs/agents/rules/lanes-and-claims.md",
            "idea_path_blocking": idea / "path-claim-blocking.md",
            "idea_path_closure": idea / "path-closure.md",
        }

    def test_agents_has_path_claims_hard_rule_section(self, docs):
        text = _read(docs["agents"])
        assert "## Path Claims — Hard Rule" in text

    def test_agents_forbids_scope_narrowing_for_claimed_paths(self, docs):
        text = _read(docs["agents"])
        assert "Claimed paths do not narrow scope" in text
        assert "Every required file stays in the item" in text
        assert "never omit, descope, or rewrite away a required file" in text

    def test_agents_states_path_claims_are_coordination_facts(self, docs):
        text = _read(docs["agents"])
        assert "coordination/dependency/blocking facts" in text
        assert "never omit, descope, or rewrite away a required file" in text

    def test_agents_requires_reference_that_enumerates_accepted_remediations(
        self, docs
    ):
        assert "Read `lanes-and-claims.md` before resolving any overlap" in _read(
            docs["agents"]
        )
        text = _read(docs["claims_reference"])
        for phrase in (
            "classify the overlap",
            "coordination_only",
            "--gate-point activation",
            'state="blocked"',
            "wait for the holder to release",
            "coordinate with the holder",
            "ask the holder to narrow or cancel",
            "steering override",
            "last resort",
        ):
            assert phrase in text, (
                f"missing accepted-remediation phrase in lanes-and-claims.md: {phrase!r}"
            )

    def test_idea_overlap_resolution_keeps_required_files(self, docs):
        assert "Never drop a required file" in _read(docs["idea_path_blocking"])
        closure = _read(docs["idea_path_closure"])
        assert "list every required file by name" in closure
        assert "[path-claim-blocking.md](path-claim-blocking.md)" in closure
