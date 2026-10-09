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
            "claims_reference": REPO
            / ".yoke/docs/reference/agent-rules/lanes-and-claims.md",
            "idea_skill": idea / "SKILL.md",
            "idea_path_closure": idea / "path-closure.md",
            "idea_infer": idea / "infer-and-create.md",
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

    def test_idea_skill_phase_3_preserves_claimed_files(self, docs):
        text = _read(docs["idea_skill"]) + _read(docs["idea_path_closure"])
        assert "Claim overlap does NOT narrow scope" in text
        assert "the file stays in the File Budget" in text
        assert "coordination/dependency/blocking facts" in text

    def test_idea_infer_create_states_no_descope_rule(self, docs):
        text = _read(docs["idea_infer"])
        assert "claimed paths do not narrow work item scope" in text
        assert "do **not** remove the file from the work item" in text
        assert "coordination/dependency/blocking facts" in text
        assert "## Path Claims — Hard Rule" in text
