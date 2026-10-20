"""Static coverage for what the steer surface teaches about its workers.

The loop's own contract is asserted next door; these cases are about the
sessions a seat launches — the launcher recipe, the DONE report's route
home, level choice and restaff — plus the discovery surfaces that have
to name `/yoke steer` for any of it to be reachable.
"""

from __future__ import annotations

import re
from pathlib import Path

from yoke_core.domain.session_launch_mandate import compose_single_item_mandate


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASH_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "dash"
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


def _worker_rules() -> str:
    return _read(_STEER_DIR / "worker-lifecycle.md") + _read(
        _STEER_DIR / "worker-launch.md"
    )


def _packet_prose(path: Path) -> str:
    """Rejoin adjacent string literals so a sentence spans source line breaks."""
    return re.sub(r'"\s*\n\s*"', "", _read(path))


def _words(text: str) -> str:
    """Collapse wrapping so a prose assertion is about words, not line breaks."""
    return " ".join(text.split())


class TestSteerWorkerLifecycle:
    def test_worker_rules_and_launcher_recipe_cover_steering_contract(self):
        text = _words(_worker_rules())
        assert "Encode every real blocker as an edge before staffing" in text
        assert "yoke items dependency list PREFIX-N --json" in text
        assert "yoke session-control launch create" in text
        assert "yoke session-control launch get" in text
        assert "yoke session-control launch reconcile" in text
        assert "yoke session-control launch retry" in text
        assert "A failed launch is reconciled or retried, never created again." in text
        assert "--level {_level}" in text
        assert "The server composes item mandates." in text
        assert "Raw mandates must forbid deployment runs" in text
        # The DONE target is the steering ROLE. A session id there would not
        # survive the seat that launched the worker being released.
        assert "yoke say --steering --stdin" in text
        assert "--session {STEERER_SESSION_ID}" not in text
        assert "yoke sessions terminate" in text
        assert "Terminate only an unresponsive worker" in text
        assert "One fresh session per item." in text
        selection = _words(_read(_STEER_DIR / "model-selection.md"))
        assert "Never pick the machine or surface." in selection

    def test_every_worker_is_taught_to_report_deliberately(self):
        mandate = compose_single_item_mandate(
            public_ref="YOK-12",
            entrypoint="/yoke dash YOK-12",
            remaining_legs="the Dash leg to its merge/evidence close",
        )
        assert "yoke say --stdin --steering" in mandate
        assert "before releasing a claim you still hold" in mandate
        assert "Ending a turn sends no Fleet message" in mandate
        assert "Do NOT create or dispatch any deployment run" in mandate

    def test_capacity_not_surface_balance_gates_launch(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "launch every runnable unclaimed scoped item" in loop
        findings = _words(_read(_STEER_DIR / "fleet-findings.md"))
        assert "Capacity does." in findings

    def test_launch_preview_is_mandatory_before_create(self):
        launch = _words(_read(_STEER_DIR / "worker-launch.md"))
        assert "Preview, then create; no other path after a refusal." in launch
        assert "Create only when preview says `launchable=true`." in launch
        assert launch.index("yoke session-control launch preview") < launch.index(
            "yoke session-control launch create"
        )

    def test_level_judgment_is_taught_at_the_launch_point(self):
        launch = _words(_read(_STEER_DIR / "worker-launch.md"))
        assert "Choose `--level` per [model-selection.md](model-selection.md)" in (
            launch
        )
        selection = _words(_read(_STEER_DIR / "model-selection.md"))
        for level in ("JUNIOR:", "INTERN:", "PRINCIPAL:", "omit `--level`"):
            assert level in selection


class TestSteerRestaff:
    def test_restaff_recipe_terminates_then_launches_a_successor(self):
        text = _words(_worker_rules())
        assert "## Restaff on a different model" in text
        assert "yoke items section get PREFIX-N --section 'Progress Log'" in text
        assert 'yoke sessions terminate {WORKER_SESSION_ID} --reason "restaff' in text
        assert "Ask for a checkpoint first." in text
        assert "yoke claims work holder-get PREFIX-N" in text
        assert "restaff:{PREVIOUS_LAUNCH_ID}" in text

    def test_the_mandate_carries_the_checkpoint_teaching(self):
        from yoke_core.domain.session_launch_mandate_teaching import (
            PROGRESS_CHECKPOINT_TEACHING,
            STANDING_TEACHINGS,
        )

        assert PROGRESS_CHECKPOINT_TEACHING in STANDING_TEACHINGS
        mandate = compose_single_item_mandate(
            public_ref="YOK-12",
            entrypoint="/yoke dash YOK-12",
            remaining_legs="the Dash leg to its merge/evidence close",
        )
        assert "Before stopping short of done, append a Progress Log checkpoint" in (
            mandate
        )

    def test_model_selection_points_a_live_item_at_the_restaff_recipe(self):
        text = _words(_read(_STEER_DIR / "model-selection.md"))
        assert "launch a new session for the next item" not in text
        assert (
            "only by [restaff](worker-lifecycle.md#restaff-on-a-different-model)"
            in (text)
        )

    def test_dash_resumes_a_restaffed_item_from_its_checkpoint(self):
        claim = _words(_read(_DASH_DIR / "file-and-claim.md"))
        assert "On resume read the Progress Log and the lane's `git status`" in claim
        assert "lane state wins" in claim
        assert "yoke items progress-log append ITEM" in claim


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
        assert "item-bound" in notes
        assert "yoke say --item PREFIX-N --stdin" in notes
        assert "A `DONE PREFIX-N` heading names the reported item" in notes


class TestSteerContinuity:
    def test_every_harness_starts_the_watcher_and_keeps_its_declared_path(self):
        from yoke_core.domain.agents_render_conditional import apply_conditional_blocks

        skill = _read(_STEER_DIR / "SKILL.md")
        loop = _read(_STEER_DIR / "loop.md")
        watching = _read(_STEER_DIR / "watching.md")
        assert "[watching.md](watching.md)" in skill
        assert "reattach the running watcher or re-arm it when absent" in _words(loop)
        for harness in ("claude", "codex", "cursor"):
            rendered = apply_conditional_blocks(watching, harness)
            assert "yoke watch fleet --print-streaming-pair" in rendered
            assert "**Stop looping**" in rendered
            assert "operator paused steering" in rendered
            assert "--mode steer" in rendered
            assert "each held project" in rendered
            assert ("`exec_command`" in rendered) == (harness == "codex")
            assert ("`Monitor`" in rendered) == (harness == "claude")
            assert ("`notify_on_output`" in rendered) == (harness == "cursor")
        codex = _words(apply_conditional_blocks(watching, "codex"))
        assert "`write_stdin`" in codex

    def test_acknowledgement_requires_disposition_and_full_scope_reconciliation(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert (
            "Read each full message, acknowledge it, then act, record a hold, or "
            "surface the decision this pass" in loop
        )
        assert "launch every runnable unclaimed scoped item" in loop
        assert "Carry seats, owners, blockers, next steps and operator actions" in loop

    def test_every_reply_preserves_all_operator_actions(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert (
            "Every operator-visible reply lists each outstanding operator action "
            "and what it unblocks" in skill
        )
        assert "never a separate nag turn" in skill


class TestSteerDependencyWait:
    def test_workers_park_for_the_dependency_notice(self):
        from yoke_core.domain.session_launch_mandate_teaching import (
            DEPENDENCY_WAIT_TEACHING,
            STANDING_TEACHINGS,
        )

        assert DEPENDENCY_WAIT_TEACHING in STANDING_TEACHINGS
        delivery = _read(_REPO_ROOT / ".yoke/docs/agents/rules/delivery.md")
        assert "## Wait on another item's merge or delivery" in delivery
