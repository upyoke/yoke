"""Watcher teaching releases only a caller with a verified wake route.

A launched headless worker is one important no-wake case, but operator-opened
and unknown surfaces must not be assumed reachable either. These tests hold
the Dash close-out steps, usher merge step, worker mandate, packet recipe, and
watcher help to the derived reachability split and every terminal wait
outcome. The in-turn wait consumes a cadence-limited server record rather
than repeating GitHub reads on the worker machine.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read
from yoke_core.domain.schema_api_context_commands_watchers import (
    WATCHERS_COMMANDS,
)
from yoke_core.domain.session_launch_mandate import (
    HEADLESS_LANDING_WAIT_TEACHING,
    compose_single_item_mandate,
)
from yoke_core.domain.standalone_item_merge_cli_parser import build_parser
from yoke_core.tools import watch_merge


DASH_CLOSE = SKILLS / "dash" / "verification-and-close.md"
USHER_MERGE = SKILLS / "usher" / "merge.md"
WORKER_LIFECYCLE = SKILLS / "steer" / "worker-lifecycle.md"
BUNDLE_SKILLS = (
    REPO / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke"
)
WATCH_MERGE_SOURCE = Path(watch_merge.__file__)
WATCHERS_PACKET_SOURCE = (
    REPO
    / "packages/yoke-core/src/yoke_core/domain"
    / "schema_api_context_commands_watchers.py"
)
COMMAND_REFERENCE = REPO / "docs/public/reference/commands.md"
BUNDLE_COMMAND_REFERENCE = (
    REPO
    / "packages/yoke-core/src/yoke_core/install_bundle_tree"
    / "docs/public/reference/commands.md"
)

# The blanket prohibition the in-turn wait replaces. A surface still
# carrying it tells a launched worker the one thing it must not do.
RETIRED_BLANKET_PROHIBITIONS = (
    "Claude must never pass `--wait`",
    "Claude never passes `--wait`",
    "Claude never blocks on --wait",
    "Claude must not pass merge-item --wait",
    "Two-call handoff — an operator-opened session.",
    "A session a person opened takes the two-call handoff.",
    "process-safe operators and Codex/Cursor, never Claude",
)


def _words(text: str) -> str:
    """Collapse wrapping so prose assertions do not depend on line breaks."""
    return " ".join(text.split())


def _mandate() -> str:
    return compose_single_item_mandate(
        public_ref="YOK-12",
        entrypoint="/yoke dash YOK-12",
        remaining_legs="the Dash leg to its merge/evidence close",
    )


def _outcome(text: str, label: str) -> str:
    """The bullet for one landing outcome, up to the next bullet or blank."""
    body = text.split(f"- **{label}**", 1)[1]
    return _words(body.split("\n- **", 1)[0].split("\n\n", 1)[0])


def _merge_recipe() -> dict:
    for entry in WATCHERS_COMMANDS:
        if "watch merge" in entry["recipe"]:
            return entry
    raise AssertionError("no watch merge recipe in the watcher packet")


def test_dash_close_out_routes_the_landing_by_derived_reachability():
    content = _words(_read(DASH_CLOSE))
    assert "one watcher invocation whose safe wait shape is resolved" in content
    assert "manifest wake capability and current control-plane reachability" in content
    assert "Never choose the route from who opened the session" in content
    assert "A verified wake route preserves the background subscription" in content
    assert "no route, or an unknown answer, keeps the wait" in content
    assert "at `reviewing-implementation` with nobody to close it out" in content
    assert "Reachability-routed wait." in content
    assert (
        "yoke watch merge --print-streaming-pair merge-item -- ITEM --wait" in content
    )
    assert "four-fact landing readback" in content
    assert "armed, queued, eligible, required checks" in content
    assert "never needs a hand-authored `gh` poll loop" in content
    assert "Read the wrapper's `wait_mode` and reason" in content
    assert "`background-wake` means the caller has a verified route" in content
    assert "`in-turn` means the same invocation is already holding" in content
    assert "No later completion notice is expected" in content
    assert "yoke github merge-queue readiness ITEM --json" in content
    assert "queue-entry=AWAITING_CHECKS" in content
    assert "consumed and in flight, not cleared" in content
    assert "merge_queue.landing.observe" in content
    assert "one project-wide GitHub sweep per cadence" in content
    assert "waiting machine issues no `gh`, GitHub, or `git fetch` read loop" in content
    assert "none of them is silence" in content


def test_dash_close_out_names_every_way_the_in_turn_wait_ends():
    wait = _read(DASH_CLOSE).split("**Reachability-routed wait.**", 1)[1]
    # Merged closes the item out inside the same turn — no second pass.
    merged = _outcome(wait, "merged")
    assert "exit 0" in merged
    assert "closed the item out in this turn" in merged
    # An ejection is a rebase, a re-gate, and a re-run of the same command.
    stopped = _outcome(wait, "landing stopped")
    assert "exit 9" in stopped
    assert "rebase the lane onto the base branch" in stopped
    assert "re-run the verification gate" in stopped
    assert "converges on the merge if one happened meanwhile" in stopped
    # A red required check is terminal for this tree, not a wait.
    red = _outcome(wait, "a required check already red")
    assert "exit 1, terminal for this tree" in red
    stale = _outcome(wait, "landing record stale")
    assert "landing_record_stale" in stale
    assert "last record/project refresh times" in stale
    assert "Do not substitute local polling" in stale
    # The bounded deadline parks with the state it read, and only then.
    deadline = _outcome(wait, "wait budget exhausted")
    assert "exit 9" in deadline
    assert "last observed reading" in deadline
    assert (
        'yoke sessions touch --mode parked --reason "<observed landing state>"'
        in deadline
    )
    assert "HUMAN_GATE" in deadline
    assert "The item stays non-terminal and the claim stays held" in deadline


def test_usher_merge_step_routes_the_landing_the_same_way():
    content = _words(_read(USHER_MERGE))
    assert "manifest capability plus current reachability" in content
    assert "Do not choose from the executor, launch origin" in content
    assert "dash/verification-and-close.md" in content
    assert "Only `background-wake` may release the selector" in content
    assert "`in-turn` is already blocking" in content


def test_every_launched_worker_mandate_carries_the_in_turn_landing_wait():
    assert HEADLESS_LANDING_WAIT_TEACHING in _mandate()
    teaching = HEADLESS_LANDING_WAIT_TEACHING
    assert "headless command that cannot be prompted again" in teaching
    assert "do not end the pass on it" in teaching
    assert "pass --wait and hold the turn on the merge watcher wrapper" in teaching
    assert "Merged closes the item out in that same turn" in teaching
    assert "a stopped landing rebases, re-runs the verification gate" in teaching
    assert "stale server landing record names its last refresh" in teaching
    assert "wait budget running out ends the turn" in teaching
    assert "--mode parked" in teaching
    assert "HUMAN_GATE" in teaching
    assert "Never end a turn on a landing you did not read." in teaching


def test_worker_lifecycle_copy_of_the_mandate_matches_the_composed_one():
    content = _read(WORKER_LIFECYCLE)
    assert HEADLESS_LANDING_WAIT_TEACHING in content
    collapsed = _words(content)
    assert "Every launched worker, whatever its origin, is a headless command" in (
        collapsed
    )
    assert "waiting for a re-entry nobody could make" in collapsed


def test_watcher_teaching_surfaces_name_the_split_not_a_blanket_ban():
    notes = _merge_recipe()["notes"]
    assert "verified wake route" in notes
    assert "callers with no or unknown reachability stay in-turn" in notes
    assert "yoke github merge-queue readiness PREFIX-N --json" in notes
    assert "null arming with an entry means consumed" in notes
    epilog = _words(_read(WATCH_MERGE_SOURCE))
    assert "a verified wake route gets the background" in epilog
    assert "headless, unreachable, or unknown callers stay in-turn" in epilog


def test_command_reference_conditions_any_later_completion_message():
    for path in (COMMAND_REFERENCE, BUNDLE_COMMAND_REFERENCE):
        content = _words(_read(path))
        assert (
            "manifest wake capability and current control-plane reachability" in content
        )
        assert "a verified route gets the background subscription" in content
        assert "no route or an unknown answer blocks in-turn" in content
        assert "rely on a later completion message only when" in content


def test_merge_wait_help_routes_from_reachability_not_executor_name():
    help_text = _words(build_parser().format_help())
    assert "watch merge wrapper" in help_text
    assert "no or unknown wake route stays in-turn" in help_text
    assert "only a verified route may release" in help_text
    assert "Codex/Cursor" not in help_text


def test_no_teaching_surface_still_carries_the_retired_blanket_prohibition():
    surfaces = (
        DASH_CLOSE,
        USHER_MERGE,
        WORKER_LIFECYCLE,
        BUNDLE_SKILLS / "dash" / "verification-and-close.md",
        BUNDLE_SKILLS / "usher" / "merge.md",
        BUNDLE_SKILLS / "steer" / "worker-lifecycle.md",
        COMMAND_REFERENCE,
        BUNDLE_COMMAND_REFERENCE,
        WATCH_MERGE_SOURCE,
        WATCHERS_PACKET_SOURCE,
    )
    for path in surfaces:
        content = _read(path)
        for retired in RETIRED_BLANKET_PROHIBITIONS:
            assert retired not in content, f"{path} still teaches {retired!r}"
