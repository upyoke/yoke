"""Tests for yoke_core.domain.session — do-loop contract + decision priority.

Shared residual suite: do-loop orchestration contract assertions and
decision priority ordering against ``decide_next_action``.

Focused unit tests live in child files:
  - test_session_imports.py: import-hygiene smoke tests and the
    SessionOffer.supported_paths field shape
  - test_session_start_*: SessionOffer, NextAction, ActionKind, FrontierState,
    ClaimedWork, decide_next_action (resume/charge/feed/strategize/escalate/wait paths)
  - test_session_render_{routing,lane,resume}.py: path derivation, lane routing,
    drift-review routing, resume compatibility, no-progress detection
"""

from __future__ import annotations

import re

import os
import sys
from pathlib import Path
from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    SessionOffer,
    decide_next_action,
)

# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DO_LOOP_PATH = _REPO_ROOT / ".claude" / "skills" / "yoke" / "do" / "loop.md"
_DO_SKILL_PATH = _REPO_ROOT / ".claude" / "skills" / "yoke" / "do" / "SKILL.md"


def _make_offer(**overrides):
    """Helper to create a SessionOffer with sensible defaults."""
    defaults = {
        "session_id": "test-session-001",
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


class TestDoLoopContract:
    """Static regression coverage for the /yoke do orchestration instructions."""

    def _loop_text(self) -> str:
        loop_dir = _DO_LOOP_PATH.parent
        return "\n\n".join(
            [
                _DO_LOOP_PATH.read_text(encoding="utf-8"),
                (loop_dir / "loop-routing.md").read_text(encoding="utf-8"),
                (loop_dir / "loop-followups.md").read_text(encoding="utf-8"),
            ]
        )

    def test_loop_passes_no_session_id(self):
        """The loop must not hand the server a session id it resolved itself.

        Ambient resolution returns the same session on every iteration, so
        an environment prefix or an explicit flag adds nothing — and passing
        identity is how a locally guessed value reaches the server at all.
        """
        text = self._loop_text()
        assert "yoke sessions identity" in text
        assert '--session-id "$YOKE_SESSION_ID"' not in text
        assert 'YOKE_SESSION_ID="' not in text
        assert "YOKE_SESSION_ID=$" not in text

    def test_loop_passes_step_to_shared_path(self):
        text = self._loop_text()
        assert '--step "{step}"' in text

    def test_loop_references_contract_event_names(self):
        """Loop references events for documentation but does not emit them directly."""
        text = self._loop_text()
        assert "HarnessSessionOffered" in text
        assert "NextActionChosen" in text
        assert "ModeChosen" not in text

    def test_loop_delegates_event_emission_to_shared_path(self):
        """Canonical emission is in shared offer path, not the loop."""
        text = self._loop_text()
        assert "shared offer path" in text
        assert "yoke sessions offer" in text
        # The loop must route event emission through the shared Python path.
        assert "emit-event.sh" not in text

    def test_loop_no_longer_starts_keepalive_loop(self):
        """Keepalive eliminated; events drive liveness.

        The PreToolUse heartbeat hook (FR-3 Option B) refreshes
        activity at agent turn boundaries instead of a background
        process. The loop's pre-dispatch checkpoint plus the handler
        dispatch remain; the keepalive setup + post-handler kill no
        longer appear in the loop prose.
        """
        text = self._loop_text()
        assert "--keepalive" not in text
        assert "YOKE_HEARTBEAT_PID" not in text
        assert "run_keepalive" not in text

    def _loop_commands(self) -> str:
        """Every fenced command block across the loop files, concatenated.

        Prose may name a flag in order to forbid it; a command block may not
        carry one. Checking the blocks keeps the guard on what an agent
        actually runs.
        """
        return "\n".join(
            re.findall(r"```(?:bash|sh|text)?\n(.*?)```", self._loop_text(), re.S)
        )

    def test_loop_commands_carry_no_identity_of_their_own(self):
        """No retired identity flag may appear in a loop command block.

        Two identical sessions in one checkout reached opposite outcomes
        purely on whether their shell variables happened to be empty when
        these flags were assembled. ``--lane`` is banned here even though the
        offer surface still honours it: it is a deliberate operator re-route,
        and a loop that fills it in is exactly how a locally guessed lane
        reached the server.
        """
        commands = self._loop_commands()
        assert commands, "no fenced command blocks found in the loop files"
        for flag in (
            "--executor", "--provider", "--workspace", "--lane", "--model",
            "--supported-paths",
        ):
            # Whole-flag match: ``--lane-role`` is a worktree lane role and
            # has nothing to do with a session's execution lane.
            assert not re.search(rf"{re.escape(flag)}(?![-\w])", commands), (
                f"loop command block still passes {flag}"
            )

    def test_loop_prose_forbids_resolving_a_lane(self):
        """The loop must say why the operator override is not its to send."""
        text = self._loop_text()
        assert "operator re-route" in text
        for shell_var in ("$_executor", "$_provider", "$_workspace", "$_lane"):
            assert shell_var not in text, f"loop still substitutes {shell_var}"

    def test_loop_reads_identity_from_the_authority(self):
        """The loop names the one call and the values it returns."""
        text = self._loop_text()
        assert "yoke sessions identity" in text
        for field in (
            "execution_lane", "lane_allowed_paths", "max_chain_steps",
            "executor_display_name",
        ):
            assert field in text, f"loop does not name {field}"

    def test_loop_relies_on_server_derived_supported_paths(self):
        """Loop declares no capability of its own; the server derives them."""
        text = self._loop_text()
        assert "YOKE_SUPPORTED_PATHS" not in text
        assert "lane_allowed_paths" in text

    def test_loop_does_not_hardcode_executor_provider_in_offers(self):
        """No hardcoded claude-code/anthropic in session-offer calls."""
        text = self._loop_text()
        # The defaults are in the env resolution line, not in the offer call
        # The session-offer call should use $_executor / $_provider variables
        assert '--executor "claude-code"' not in text
        assert '--provider "anthropic"' not in text

    def test_loop_identity_fields_present(self):
        """Identity fields referenced in the loop (via CLI args or env vars)."""
        text = self._loop_text()
        for field in ("executor", "provider", "model", "workspace", "session-id"):
            assert field in text

    def test_loop_guidance_does_not_double_prefix_ids(self):
        text = self._loop_text()
        assert "PREFIX-{item_id}" not in text
        assert "PREFIX-{first_runnable_item}" not in text
        assert "/yoke conduct {item_id}" in text
        assert "/yoke conduct {selected_item}" in text
        assert "/yoke conduct PREFIX-{epic_id}" in text

    def test_loop_charge_dispatches_from_scheduler_next_step(self):
        text = self._loop_text()
        assert "context.scheduler.next_step" in text
        assert "/yoke shepherd {selected_item}" in text
        assert "/yoke usher {selected_item}" in text

    def test_loop_resume_guidance_is_status_aware(self):
        text = self._loop_text()
        assert "context.status" in text
        assert "/yoke shepherd {item_id}" in text
        assert "/yoke usher {item_id}" in text
        assert (
            "RESUME: Continuing work on epic PREFIX-{epic_id} task #{task_num}" in text
        )

    def test_do_skill_notes_reference_scheduler_next_step(self):
        text = _DO_SKILL_PATH.read_text(encoding="utf-8")
        assert "context.scheduler.next_step" in text
        assert "dispatch based on item type" not in text

    def test_do_skill_documents_identity_read_back(self):
        """SKILL.md teaches ``yoke sessions identity`` as the identity owner.

        Agents read the stored values back. They do not resolve, detect, or
        mint any of them, and they pass none of them onward. Cursor is a
        first-class executor.
        """
        text = _DO_SKILL_PATH.read_text(encoding="utf-8")
        assert "yoke sessions identity" in text
        assert "yoke sessions init" not in text
        assert "Do not" in text
        assert "never mint" in text.lower()
        assert "Cursor is a" in text
        assert "YOKE_MODEL" not in text
        assert "CLAUDE_MODEL" not in text
        assert "YOKE_SUPPORTED_PATHS" not in text
        assert "derived server-side" in text
        assert "Identity is server-resolved" in text

    def test_do_skill_documents_shared_path_emission(self):
        """SKILL.md documents canonical emission in shared offer path."""
        text = _DO_SKILL_PATH.read_text(encoding="utf-8")
        assert "shared `yoke sessions offer` path" in text


# ---------------------------------------------------------------------------
# decide_next_action — priority ordering comprehensive
# ---------------------------------------------------------------------------


class TestDecisionPriorityOrdering:
    """Verify the strict priority ordering: resume > charge > escalate > feed (graph stale) > feed (no items) > strategize > wait."""

    def test_resume_beats_everything(self):
        """Resume wins even with runnable items, blocked items, and incoherent SML."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            blocked_items=["YOK-2"],
            sml_coherent=False,
        )
        claims = [ClaimedWork(item_id="YOK-99", status="active")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME

    def test_charge_beats_escalate_feed_strategize(self):
        """When runnable items and coherent SML, charge wins."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            blocked_items=["YOK-2"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_escalate_beats_feed_and_strategize(self):
        """When all items are blocked (no runnable), escalate wins over feed/strategize."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-5"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE

    def test_feed_beats_strategize_when_coherent(self):
        """Empty frontier + coherent SML -> feed (not strategize)."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED

    def test_strategize_when_sml_broken(self):
        """Incoherent SML with empty frontier -> strategize."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=False,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_escalate_includes_all_blocked_items(self):
        """Escalate context should list all blocked items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-1", "YOK-2", "YOK-3"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert len(result.context["blocked_items"]) == 3

    def test_feed_context_includes_blocked_count(self):
        """Feed context blocked_count should be 0 when no blocked items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["blocked_count"] == 0

    def test_strategize_context_includes_sml_coherent(self):
        """Strategize context should include sml_coherent."""
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.context["sml_coherent"] is False
