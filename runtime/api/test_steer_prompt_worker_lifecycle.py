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
    """Normalize whitespace in command examples."""
    return " ".join(text.split())


class TestSteerWorkerLifecycle:
    def test_worker_rules_and_launcher_recipe_cover_steering_contract(self):
        text = _words(_worker_rules())
        assert "yoke items dependency list PREFIX-N --json" in text
        assert "yoke session-control launch create" in text
        assert "yoke session-control launch get" in text
        assert "yoke session-control launch reconcile" in text
        assert "yoke session-control launch retry" in text
        assert (
            "yoke session-control launch create --project {_project} --item {ITEM} "
            '--idempotency-key "steer:{_project}:{ITEM}" --json'
        ) in text
        # The DONE target is the steering ROLE. A session id there would not
        # survive the seat that launched the worker being released.
        assert "yoke say --steering --stdin" in text
        assert "--session {STEERER_SESSION_ID}" not in text
        assert "yoke sessions terminate" in text

    def test_worker_mandate_reports_to_steering(self):
        mandate = compose_single_item_mandate(
            public_ref="YOK-12",
            entrypoint="/yoke dash YOK-12",
            remaining_legs="the Dash leg to its merge/evidence close",
        )
        assert "yoke say --stdin --steering" in mandate

    def test_launch_preview_is_mandatory_before_create(self):
        launch = _words(_read(_STEER_DIR / "worker-launch.md"))
        assert launch.index("yoke session-control launch preview") < launch.index(
            "yoke session-control launch create"
        )

    def test_the_default_launch_names_no_level_or_placement(self):
        launch = _words(_read(_STEER_DIR / "worker-launch.md"))
        preview = "yoke session-control launch preview --project {_project} --item {ITEM}"
        assert preview in launch
        assert "{_level}" not in launch
        assert "[level](model-selection.md)" in launch
        assert "level-launches.md#overrides" in launch

    def test_level_override_is_taught_against_the_stage_level(self):
        selection = _words(_read(_STEER_DIR / "model-selection.md"))
        assert "only when the work needs a level other than the item's effective stage level" in selection
        assert "`yoke settings get levels`" in selection
        assert "--level-reason" in selection
        assert "PRINCIPAL launches and restaff require explicit operator approval" in selection
        assert "level-launches.md#overrides" in selection
        for listed in ("JUNIOR:", "INTERN:", "SENIOR"):
            assert listed not in selection


class TestSteerRestaff:
    def test_restaff_recipe_terminates_then_launches_a_successor(self):
        text = _words(_worker_rules())
        assert "## Restaff on a different model" in text
        assert "yoke items section get PREFIX-N --section 'Progress Log'" in text
        assert 'yoke sessions terminate {WORKER_SESSION_ID} --reason "restaff' in text
        assert "yoke claims work holder-get PREFIX-N" in text
        assert "restaff:{PREVIOUS_LAUNCH_ID}" in text

    def test_the_mandate_carries_the_checkpoint_teaching(self):
        from yoke_core.domain.session_launch_mandate_teaching import (
            PROGRESS_CHECKPOINT_TEACHING,
            STANDING_TEACHINGS,
        )

        assert PROGRESS_CHECKPOINT_TEACHING in STANDING_TEACHINGS

    def test_model_selection_links_to_the_restaff_recipe(self):
        text = _read(_STEER_DIR / "model-selection.md")
        assert "[restaff](worker-lifecycle.md#restaff-on-a-different-model)" in text

    def test_dash_checkpoint_command(self):
        claim = _words(_read(_DASH_DIR / "file-and-claim.md"))
        assert "yoke items progress-log append ITEM" in claim


class TestSteerDiscoveryAndPacket:
    def test_router_and_help_name_steer(self):
        assert "/yoke steer" in _read(_ROUTER)
        assert "/yoke steer" in _read(_HELP)

    def test_packet_teaches_steer_loop_and_fleet_report(self):
        notes = _packet_prose(_CLAIMS_PACKET)
        assert "/yoke steer [SLUG] [--project P ...]" in notes
        assert "--doc SLUG" in notes
        assert "`--plan-doc`" in notes
        assert "yoke steering report get" in notes
        assert "`--project P`" in notes
        assert "yoke say --item PREFIX-N --stdin" in notes


class TestSteerContinuity:
    def test_harness_watcher_commands_and_phase_link(self):
        from yoke_core.domain.agents_render_conditional import apply_conditional_blocks

        skill = _read(_STEER_DIR / "SKILL.md")
        assert "[watching.md](watching.md)" in skill
        watching = _read(_STEER_DIR / "watching.md")
        for harness in ("claude", "codex", "cursor"):
            rendered = apply_conditional_blocks(watching, harness)
            assert "yoke watch fleet --print-streaming-pair" in rendered
            assert "sessions touch --mode wait" in rendered
            assert ("`exec_command`" in rendered) == (harness == "codex")
            assert ("`Monitor`" in rendered) == (harness == "claude")
            assert ("`notify_on_output`" in rendered) == (harness == "cursor")
        codex = _words(apply_conditional_blocks(watching, "codex"))
        assert "`write_stdin`" in codex


class TestSteerDependencyWait:
    def test_workers_park_for_the_dependency_notice(self):
        from yoke_core.domain.session_launch_mandate_teaching import (
            DEPENDENCY_WAIT_TEACHING,
            STANDING_TEACHINGS,
        )

        assert DEPENDENCY_WAIT_TEACHING in STANDING_TEACHINGS
        delivery = _read(_REPO_ROOT / ".yoke/docs/agents/rules/delivery.md")
        assert "## Wait on another item's merge or delivery" in delivery
