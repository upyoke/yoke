"""Static coverage for what the steer surface teaches about its workers.

The loop's own contract is asserted next door; these cases are about the
sessions a seat launches — the launcher recipe, the DONE report's route
home, and the surface-choice rules — plus the discovery surfaces that have
to name `/yoke steer` for any of it to be reachable.
"""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEER_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "steer"
_ROUTER = _REPO_ROOT / ".agents" / "skills" / "yoke" / "SKILL.md"
_HELP = _REPO_ROOT / ".agents" / "skills" / "yoke" / "help" / "SKILL.md"
_CLAIMS_PACKET = (
    _REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "domain"
    / "schema_api_context_commands_claims.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _packet_prose(path: Path) -> str:
    """Rejoin adjacent string literals so a sentence spans source line breaks."""
    return re.sub(r'"\s*\n\s*"', "", _read(path))


def _words(text: str) -> str:
    """Collapse wrapping so a prose assertion is about words, not line breaks."""
    return " ".join(text.split())


class TestSteerWorkerLifecycle:
    def test_worker_rules_and_launcher_recipe_cover_steering_contract(self):
        text = _read(_STEER_DIR / "worker-lifecycle.md")
        assert "Encode dependency edges" in text
        assert "Keep the frontier maxed out" in text
        assert "Launch CLI surfaces only" in text
        assert "Route one item through its pinned workflow" in text
        assert "Workers self-end after their DONE report" in text
        assert "Every new item gets a fresh session" in text
        assert "Choose model, effort, and context per item at launch" in text
        assert "yoke session-control launch create" in text
        assert "yoke session-control launch get" in text
        assert "yoke session-control launch reconcile" in text
        assert "yoke session-control launch retry" in text
        assert "claude-cli" in text
        assert "codex-cli" in text
        assert "cursor-cli" in text
        assert "Allocate by headroom, not by leveling counts" in text
        # The seat chooses the surface; the launch plane chooses the machine.
        assert "Do not pick the machine" in text
        assert "placement_reason" in text
        assert "machine_access_denied" in text
        assert "preferred_session_models" in text
        assert "yoke sessions terminate" in text
        assert "reserved for an unresponsive worker" in text
        assert "Single-item mandate (steering)" in text
        assert "Do NOT create or dispatch any deployment run" in text
        assert "yoke workflows item get PREFIX-N" in text
        assert "/yoke refine PREFIX-N" in text
        assert "/yoke blitz PREFIX-N" in text
        assert "/yoke shepherd" in text
        assert "yoke say --item PREFIX-N --stdin" in text
        # The DONE target is the steering ROLE. A session id there would not
        # survive the seat that launched the worker being released.
        assert "yoke say --steering" in text
        assert "--session {STEERER_SESSION_ID}" not in text
        assert "never pad, complete, or expand one by hand" in text
        assert "yoke session-control launch preview" in text
        assert "Do not hand-assemble" in text
        assert "the server composes it" in text

    def test_every_worker_is_taught_to_report_deliberately(self):
        text = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Every worker sends the report deliberately" in text
        assert "The PREFIX-N in the heading is the report identity" in text
        assert "Ending a turn sends no Fleet message" in text
        assert "Every worker gets the `yoke say --steering` DONE step" in text
        assert "before releasing any claim it still holds" in text
        assert "Launch origin does not change that boundary" in text
        assert "session_control.launch.preview" in _read(_STEER_DIR / "SKILL.md")
        assert "session_control.launch.list" in _read(_STEER_DIR / "SKILL.md")

    def test_surfaces_are_not_exclusive_and_balance_is_not_a_quota(self):
        text = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Surfaces are not exclusive" in text
        assert "as many concurrent sessions as the work needs" in text
        assert "one-session-per-surface cap" in text
        assert "There is no per-surface session cap" in text
        assert "never withholds a launch" in text

    def test_launch_preview_is_mandatory_and_names_surface_refusals(self):
        text = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Preview the chosen CLI surface before every launch" in text
        assert "never the calling session's own surface" in text
        assert "unsupported_surface" in text
        assert "A refusal names the surface, not the item" in text
        assert "launchable=true" in text
        assert "Do not create until preview returns" in text


class TestSteerDiscoveryAndPacket:
    def test_router_and_help_name_steer(self):
        assert "/yoke steer" in _read(_ROUTER)
        assert "/yoke steer" in _read(_HELP)

    def test_packet_teaches_steer_loop_and_fleet_report(self):
        notes = _packet_prose(_CLAIMS_PACKET)
        assert "/yoke steer [SLUG] [--project P ...]" in notes
        assert "resolves to CURRENT-PLAN per named project" in notes
        assert "is never a question to ask" in notes
        assert "only a genuinely missing doc reaches the offer-to-create gate" in notes
        assert "--doc SLUG" in notes
        assert "narrows the seat to that document's linked items" in notes
        assert "`--plan-doc` locks the standing plan" in notes
        assert "yoke steering report get" in notes
        assert "optional `--project P`" in notes
        assert "never `/yoke do`" in notes
        assert "yoke say --item PREFIX-N --stdin" in notes
        assert "A `DONE PREFIX-N` heading names the reported item" in notes


class TestSteerContinuity:
    def test_every_harness_starts_the_watcher_and_keeps_its_declared_path(self):
        from yoke_core.domain.agents_render_conditional import apply_conditional_blocks

        loop = _read(_STEER_DIR / "loop.md")
        watching = _read(_STEER_DIR / "watching.md")
        assert "[watching.md](watching.md) completely" in loop
        for harness in ("claude", "codex", "cursor"):
            rendered = apply_conditional_blocks(watching, harness)
            assert "yoke watch fleet --print-streaming-pair" in rendered
            assert "explicit **stop looping**" in rendered
            assert "--mode parked" in rendered and "--mode steer" in rendered
            assert "compaction" in rendered and "subscription loss" in rendered
            assert "every held project" in rendered
            assert ("`exec_command`" in rendered) == (harness == "codex")
            assert ("`Monitor`" in rendered) == (harness == "claude")
            assert ("`notify_on_output`" in rendered) == (harness == "cursor")
        codex = _words(apply_conditional_blocks(watching, "codex"))
        assert "`write_stdin`" in codex
        assert "answered in commentary while work continues" in codex
        assert "An explicit" in codex
        assert "ordinary questions, hooks and compaction" in codex

    def test_acknowledgement_requires_disposition_and_full_scope_reconciliation(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "acknowledge immediately, then assign a substantive disposition" in loop
        assert "that heading is the report identity" in loop
        assert "act now, record the exact dependency/hold" in loop
        assert "surface the reserved operator decision" in loop
        assert "Acknowledgement is receipt, never completion" in loop
        assert "Carry unfinished actions in CURRENT-PLAN" in loop
        assert "before switching topics or ending this pass" in loop
        assert "all runnable scoped work" in loop
        assert "launch or restaff each authorized unclaimed item" in loop
        assert "unblock and resume cleared dependents" in loop

    def test_every_reply_preserves_all_operator_actions_with_verified_attribution(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "Every operator-visible reply/turn" in loop
        assert "all live outstanding operator actions" in loop
        assert "the specific required action, and what it unblocks" in loop
        assert "until resolved or explicitly muted" in loop
        assert "ordinary questions never waive this duty" in loop
        assert "never a separate wake or turn just to nag" in loop
        assert "verify the actual authority" in loop
        assert "If a system failure caused the hold, correct the attribution" in loop
        assert "standing plan's live status section" in loop
