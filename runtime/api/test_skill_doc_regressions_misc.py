"""Misc skill-doc regressions: system simulation canonical agents + reflection capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    AGENTS,
    REPO,
    SKILLS,
    _read,
    _read_dispatch_context,
)


class TestSystemSimulationCanonicalAgents:
    """System-wide simulation must read canonical agent bodies, not Claude as truth."""

    def test_system_simulation_reads_canonical_agent_bodies(self):
        text = _read(SKILLS / "simulate" / "system.md")
        assert "Canonical agent bodies: all `runtime/agents/*.md`" in text
        assert "{contents of each runtime/agents/*.md file, labeled with filename}" in text

    def test_system_simulation_does_not_treat_claude_agents_as_canonical(self):
        text = _read(SKILLS / "simulate" / "system.md")
        assert "Agent definitions: all `.claude/agents/yoke-*.md`" not in text
        assert "{contents of each .claude/agents/yoke-*.md file, labeled with filename}" not in text


class TestReflectionCaptureDocs:
    """Reflection-capture docs must stay aligned on parent-owned persistence."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "dispatch_context": SKILLS / "conduct" / "dispatch-context.md",
            "engineer": AGENTS / "yoke-engineer.md",
            "tester": AGENTS / "yoke-tester.md",
            "simulator": AGENTS / "yoke-simulator.md",
            "agents_doc": REPO / "docs" / "agents.md",
        }

    def test_dispatch_context_names_hook_capture_path(self, docs):
        # Post-YOK-1832: capture moved from skill-prose recipe to the
        # PostToolUse Agent-tool hook. The hook module must be named
        # in the conduct dispatch artifacts so future agents see WHO
        # captures reflections.
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "yoke_core.domain.reflection_capture_hook" in text

    def test_dispatch_context_does_not_hardcode_context_placeholder(self, docs):
        text = _read_dispatch_context(docs["dispatch_context"])
        assert '"conduct YOK-${_id}"' not in text

    def test_dispatch_context_no_longer_manual_capture_recipe(self, docs):
        # Post-YOK-1832: the manual mktemp+reflection_capture --output-text
        # recipe was deleted in favor of the PostToolUse hook. Pin the
        # absence so it doesn't slip back in.
        text = _read_dispatch_context(docs["dispatch_context"])
        assert '--project "$_reflect_project"' not in text
        assert "_reflect_tmp=$(mktemp" not in text

    def test_agent_prompts_do_not_name_legacy_direct_insert_path(self, docs):
        legacy = "python3 -m yoke_core.cli.db_router ouroboros insert-entry"
        for key in ("engineer", "tester", "simulator"):
            assert legacy not in _read(docs[key]), f"legacy insert path still present in {key}"

    def test_agents_doc_states_hook_captured_contract(self, docs):
        # Post-YOK-1832: docs/agents.md teaches the hook-captured
        # semantics, not the legacy parent-dispatch-session contract.
        text = _read(docs["agents_doc"])
        assert "All agents use hook-captured reflection semantics." in text
        assert "PostToolUse Agent-tool hook" in text
        assert "No agent writes directly to the DB." in text


class TestNoDescopeForActivePathClaims:
    """Active path claims must not narrow ticket scope.

    A ticket's correct implementation scope must never be narrowed,
    descoped, or rewritten solely because a required path is already
    claimed. Active path claims are coordination/dependency/blocking
    facts about who currently coordinates work on a path — never
    permission to omit a required file from a ticket.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        idea = SKILLS / "idea"
        return {
            "agents": REPO / "AGENTS.md",
            "idea_skill": idea / "SKILL.md",
            "idea_infer": idea / "infer-and-create.md",
        }

    def test_agents_has_path_claims_hard_rule_section(self, docs):
        text = _read(docs["agents"])
        assert "## Path Claims — Hard Rule" in text

    def test_agents_forbids_scope_narrowing_for_claimed_paths(self, docs):
        text = _read(docs["agents"])
        assert "Claimed paths do not narrow ticket scope" in text
        assert (
            "must never be narrowed, descoped, or rewritten solely because"
            in text
        )
        assert "the file stays in the ticket" in text

    def test_agents_states_path_claims_are_coordination_facts(self, docs):
        text = _read(docs["agents"])
        assert "coordination/dependency/blocking facts" in text
        assert "never authorizes omitting a required file" in text

    def test_agents_enumerates_accepted_remediations(self, docs):
        text = _read(docs["agents"])
        for phrase in (
            "classify the overlap",
            "coordination_only",
            "--gate-point activation",
            'state="blocked"',
            "wait for the holder to release",
            "coordinate with the holder",
            "ask the holder to narrow or cancel",
            "operator override",
            "last resort",
        ):
            assert phrase in text, (
                f"missing accepted-remediation phrase in AGENTS.md: {phrase!r}"
            )

    def test_idea_skill_phase_3_preserves_claimed_files(self, docs):
        text = _read(docs["idea_skill"])
        assert "Claim overlap does NOT narrow scope" in text
        assert "the file stays in the File Budget" in text
        assert "coordination/dependency/blocking facts" in text

    def test_idea_infer_create_states_no_descope_rule(self, docs):
        text = _read(docs["idea_infer"])
        assert "claimed paths do not narrow ticket scope" in text
        assert "do **not** remove the file from the ticket" in text
        assert "coordination/dependency/blocking facts" in text
        assert "## Path Claims — Hard Rule" in text


class TestSameSessionWorktreeScopeDocs:
    """Worktree creation must be documented as a same-session scope transition."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "agents": REPO / "AGENTS.md",
            "commands": REPO / ".yoke" / "docs" / "commands.md",
            "harness": REPO / "docs" / "harness-substrate.md",
            "lifecycle": REPO / ".yoke" / "docs" / "lifecycle.md",
            "advance": SKILLS / "advance" / "SKILL.md",
            "advance_worktree": SKILLS / "advance" / "worktree.md",
            "conduct": SKILLS / "conduct" / "SKILL.md",
            "do_routing": SKILLS / "do" / "loop-routing.md",
            "do_followups": SKILLS / "do" / "loop-followups.md",
        }

    def test_shared_docs_teach_claim_based_authority(self, docs):
        # After the envelope deletion, commands.md and
        # harness-substrate.md teach the work-claim-as-authority model
        # for the same-session implementation flow. The legacy
        # SessionExecutionScopeChanged event name no longer appears in
        # the shared docs (it survives only as a RETIRED row in
        # event-catalog.md).
        for key in ("commands", "harness"):
            text = _read(docs[key])
            assert "work-claim" in text or "work_claims" in text, key
            assert "SessionExecutionScopeChanged" not in text, key

    def test_advance_docs_describe_same_session_continuation(self, docs):
        text = _read(docs["advance"])
        worktree = _read(docs["advance_worktree"])
        # The durable markers under the claim-based authority model are
        # "same harness session" + the absence of any "manual relaunch".
        assert "same harness session" in text
        assert "no manual relaunch" in worktree or "no relaunch" in worktree
        # The legacy event name no longer appears in advance prose.
        assert "SessionExecutionScopeChanged" not in worktree
        assert "SessionExecutionScopeChanged" not in text

    def test_conduct_docs_describe_same_session_continuation(self, docs):
        text = _read(docs["conduct"])
        assert "same-session" in text or "same harness session" in text
        assert "no manual relaunch" in text

    def test_do_routing_no_worktree_handoff_terminator(self, docs):
        text = _read(docs["do_routing"])
        assert "worktree-handoff" not in text
        assert "Do not re-offer" not in text

    def test_do_followups_no_session_end_for_worktree_scope_movement(self, docs):
        text = _read(docs["do_followups"])
        assert "worktree-handoff" not in text


class TestWorktreeHandoffEmittedRetired:
    """The retired event surface must be marked retired in event-catalog."""

    def test_event_catalog_marks_handoff_event_retired(self):
        text = _read(REPO / "docs" / "event-catalog.md")
        # Find the row that references WorktreeHandoffEmitted
        line = next(
            (line for line in text.splitlines() if "WorktreeHandoffEmitted" in line),
            "",
        )
        assert "RETIRED" in line or "retired" in line, line

    def test_event_catalog_marks_session_execution_scope_event_retired(self):
        text = _read(REPO / "docs" / "event-catalog.md")
        # SessionExecutionScopeChanged retired together with the session
        # envelope; the per-call claim-based lint authority replaced it.
        # The catalog row stays as a historical entry for visibility.
        line = next(
            (
                line
                for line in text.splitlines()
                if "SessionExecutionScopeChanged" in line
            ),
            "",
        )
        assert "RETIRED" in line or "retired" in line, line
