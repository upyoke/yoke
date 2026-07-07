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

    def test_loop_uses_stable_session_id(self):
        # The session-id resolution moved into ``yoke_core.tools.session_init``
        # (hotfix 8015b561c collapsed inline shell into the wrapper). The loop
        # must still teach the stable-session-id contract: invoke the wrapper
        # once, then pass ``--session-id "$YOKE_SESSION_ID"`` on the
        # re-offer call so every iteration stays attached to the same session.
        text = self._loop_text()
        assert "yoke_core.tools.session_init" in text
        assert "YOKE_SESSION_ID" in text
        assert '--session-id "$YOKE_SESSION_ID"' in text

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

    def test_loop_resolves_executor_from_env(self):
        """AC-1: executor resolution delegated to the session_init wrapper.

        Hotfix 8015b561c moved the inline ``YOKE_EXECUTOR`` / Codex
        auto-detect shell ladder into ``yoke_core.tools.session_init``.
        The loop teaches the wrapper invocation and documents the env
        var contract; the wrapper's own unit tests cover the fallback
        ladder mechanics.
        """
        text = self._loop_text()
        assert "yoke_core.tools.session_init" in text
        assert "YOKE_EXECUTOR" in text
        assert "EXECUTOR" in text  # wrapper emits ``EXECUTOR=<value>`` line
        assert '$_executor' in text  # offer call substitutes captured value

    def test_loop_resolves_provider_from_env(self):
        """AC-2: provider resolution delegated to the session_init wrapper.

        Same migration as ``test_loop_resolves_executor_from_env`` above:
        the loop teaches the wrapper invocation and the env var contract;
        the wrapper owns the executor-aware fallback ladder.
        """
        text = self._loop_text()
        assert "yoke_core.tools.session_init" in text
        assert "YOKE_PROVIDER" in text
        assert "PROVIDER" in text  # wrapper emits ``PROVIDER=<value>`` line
        assert '$_provider' in text  # offer call substitutes captured value

    def test_loop_passes_resolved_identity_to_service_client(self):
        """AC-3: Resolved identity vars are passed to service_client.py."""
        text = self._loop_text()
        assert "--executor" in text
        assert "$_executor" in text
        assert "--provider" in text
        assert "$_provider" in text

    def test_loop_relies_on_server_derived_supported_paths(self):
        """AC-4: loop no longer passes --supported-paths from harness env."""
        text = self._loop_text()
        assert "YOKE_SUPPORTED_PATHS" not in text
        assert 'No --supported-paths.' in text
        assert '--session-id "$YOKE_SESSION_ID"' in text
        assert "Server derives capabilities from shared registry plus manifest limitations" in text

    def test_loop_does_not_hardcode_executor_provider_in_offers(self):
        """AC-6: No hardcoded claude-code/anthropic in session-offer calls."""
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
        assert "YOK-{item_id}" not in text
        assert "YOK-{first_runnable_item}" not in text
        assert "/yoke conduct {item_id}" in text
        assert "/yoke conduct {selected_item}" in text
        assert "/yoke conduct YOK-{epic_id}" in text

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
        assert "RESUME: Continuing work on epic YOK-{epic_id} task #{task_num}" in text

    def test_do_skill_notes_reference_scheduler_next_step(self):
        text = _DO_SKILL_PATH.read_text(encoding="utf-8")
        assert "context.scheduler.next_step" in text
        assert "dispatch based on item type" not in text

    def test_do_skill_documents_env_var_identity(self):
        """SKILL.md documents env var resolution for executor and provider.

        The model identifier is intentionally *not* in this list (the migration
        removed the LLM-side model resolution chain (no more ``--model``
        substitution into the loop command) and the canonical value is
        read from ``harness_sessions.model`` server-side. AC-12 enforces
        that ``YOKE_MODEL`` and ``CLAUDE_MODEL`` do not appear in any
        ``.agents/skills/yoke/do/`` file. The model resolution path is
        teaching content in the Philosophy section, not part of the
        env-var identity list.
        """
        text = _DO_SKILL_PATH.read_text(encoding="utf-8")
        assert "YOKE_EXECUTOR" in text
        assert "YOKE_PROVIDER" in text
        assert "YOKE_MODEL" not in text
        assert "CLAUDE_MODEL" not in text
        assert "CODEX_THREAD_ID" in text
        assert "YOKE_SUPPORTED_PATHS" not in text
        assert "Yoke-owned harnesses self-report identity only." in text
        assert "derives harness capabilities server-side" in text
        # The new doctrine sentence is teaching content for the agent.
        assert "Model is server-resolved." in text

    def test_do_skill_documents_shared_path_emission(self):
        """AC-7: SKILL.md documents canonical emission in shared offer path."""
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
