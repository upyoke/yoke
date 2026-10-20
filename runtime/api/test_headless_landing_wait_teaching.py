"""Landing teaching splits a session that can wait from one that cannot, and
tells every caller what a handed-back call still owes.

A relay-launched session never waits: its merge arms the landing and returns,
and the control-plane notice re-enters it for close-out. Every other caller
waits, and is released to a background subscription only when its harness has
a native idle-wake primitive — a fact about the harness, not about whether
Yoke can reach the session over a relay. These tests hold the Dash close-out
steps, usher merge step, worker mandate, packet recipe, and watcher help to
that split and to every terminal wait outcome. The in-turn wait consumes a
cadence-limited server record rather than repeating GitHub reads on the worker
machine.

The other half of the same split is what a caller does when its harness hands
a still-running command back mid-turn. That hand-back is not the end of the
call, and no surface may teach that continuing it is what ends the turn, so
these tests hold the worker mandate, the Dash in-turn bullet, and the Claude
session rules to continuing the call until it exits.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read
from yoke_core.domain.schema_api_context_commands_watchers import (
    WATCHERS_COMMANDS,
)
from yoke_core.domain.session_launch_mandate import compose_single_item_mandate
from yoke_core.domain.session_launch_mandate_teaching import (
    HEADLESS_LANDING_WAIT_TEACHING,
    HEADLESS_TOOL_CONTINUATION_TEACHING,
)
from yoke_core.tools import watch_merge


DASH_MERGE = SKILLS / "dash" / "merge.md"
USHER_MERGE = SKILLS / "usher" / "merge.md"
WORKER_LIFECYCLE = SKILLS / "steer" / "worker-lifecycle.md"
CLAUDE_SESSION_RULES = REPO / "runtime/harness/claude/rules/session.md"
BUNDLE_SKILLS = (
    REPO / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke"
)
WATCH_MERGE_SOURCE = Path(watch_merge.__file__)
WATCHERS_PACKET_SOURCE = (
    REPO
    / "packages/yoke-core/src/yoke_core/domain"
    / "schema_api_context_commands_watchers.py"
)
COMMAND_REFERENCE = REPO / "docs/public/agents/commands.md"
BUNDLE_COMMAND_REFERENCE = (
    REPO
    / "packages/yoke-core/src/yoke_core/install_bundle_tree"
    / "docs/public/agents/commands.md"
)

# Prohibitions keyed on executor name rather than on what the calling
# session can actually do. A surface still carrying one routes the wait
# from who the caller is instead of from the landing handoff.
RETIRED_BLANKET_PROHIBITIONS = (
    "Claude must never pass `--wait`",
    "Claude never passes `--wait`",
    "Claude never blocks on --wait",
    "Claude must not pass merge-item --wait",
    "Two-call handoff — an operator-opened session.",
    "A session a person opened takes the two-call handoff.",
    "process-safe operators and Codex/Cursor, never Claude",
)

# Wait selection keyed on Yoke's own relay reachability rather than on the
# harness primitive that actually resumes the turn. A surface still carrying
# one holds a natively wakeable conversation foreground for nothing, because
# Monitor and notify_on_output need no control-plane route to fire.
# Teaching that read the harness's own hand-back as the end of the call. A
# surface still carrying one tells a caller that continuing its live command
# is what kills it, which leaves ending the turn as the only move.
RETIRED_HAND_BACK_AS_TURN_END = (
    "reading that task's file ends the turn",
    "reading that task's output ends the turn",
)

RETIRED_REACHABILITY_GATING = (
    "manifest wake capability and current control-plane reachability",
    "manifest capability plus current reachability",
    "a verified wake route gets the background",
    "a verified route gets the background subscription",
    "callers with no or unknown reachability stay in-turn",
    "no or unknown wake route stays in-turn",
    "no route, or an unknown answer, keeps the wait",
    "Reachability-routed wait.",
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


def _merge_recipe() -> dict:
    for entry in WATCHERS_COMMANDS:
        if "watch merge" in entry["recipe"]:
            return entry
    raise AssertionError("no watch merge recipe in the watcher packet")


def test_dash_merge_phase_hands_a_launched_landing_to_its_notice():
    content = _words(_read(DASH_MERGE))
    assert "Relay-launched: arm, report the PR and the pending landing, stop." in (
        content
    )
    assert "The landing notice wakes you to rerun." in content


def test_dash_merge_phase_prints_the_wait_shape_before_running_it():
    content = _words(_read(DASH_MERGE))
    assert (
        "yoke watch merge --print-streaming-pair merge-item -- ITEM --wait" in content
    )
    assert "run the printed command once" in content


def test_the_continuation_teaching_names_the_only_early_stops():
    teaching = HEADLESS_TOOL_CONTINUATION_TEACHING
    assert "reading the background task's output continues the call" in teaching
    assert "only ending the turn kills the watcher" in teaching
    assert "Never start a second invocation beside a live one" in teaching
    assert "a merge that returned landing_pending has its landing notice" in teaching


def test_no_teaching_surface_reads_the_hand_back_as_the_end_of_the_call():
    for path in (DASH_MERGE, WORKER_LIFECYCLE, CLAUDE_SESSION_RULES):
        content = _read(path)
        for retired in RETIRED_HAND_BACK_AS_TURN_END:
            assert retired not in content, f"{path} still teaches {retired!r}"


def test_claude_session_rules_keep_the_watcher_alive_through_a_hand_back():
    content = _words(_read(CLAUDE_SESSION_RULES))
    assert "a turn that ends there kills the watcher it was holding" in content
    assert (
        "Reading the background task's output is how you continue the call, "
        "not how you end the turn" in content
    )
    assert "keep reading until the command exits and you have its outcome" in content
    assert "A relay-launched worker has no second chance here" in content
    assert "naming the continuation before the command starts" in content


def test_dash_merge_phase_names_every_way_the_in_turn_wait_ends():
    content = _words(_read(DASH_MERGE))
    assert "Exit 0 is not done; read the `[close-out]` block." in content
    assert "Exit 9 names its recovery" in content
    assert "a red check means fix, commit, reverify" in content
    assert "Wait budget exhausted: checkpoint, park, keep the claim." in content


def test_usher_merge_step_routes_the_landing_the_same_way():
    content = _words(_read(USHER_MERGE))
    assert "yoke watch merge --print-streaming-pair merge-item --" in content
    assert "Run the printed command once." in content


def test_every_launched_worker_mandate_carries_the_landing_handoff():
    assert (
        "read its phase instructions before verification, merge or delivery"
        in _mandate()
    )
    teaching = HEADLESS_LANDING_WAIT_TEACHING
    assert "headless command that cannot be prompted again" in teaching
    assert "arms the landing and returns landing_pending=true" in teaching
    assert "whether or not you passed --wait" in teaching
    assert "That is the handoff, not a failure." in teaching
    assert "Report the pull request, stop deliberately" in teaching
    assert "say you are waiting on landing" in teaching
    assert "landing notice wakes you" in teaching
    assert "re-run the same `yoke merge item` command then" in teaching
    assert "A stopped landing arrives the same way and names its recovery" in teaching
    assert "stale server landing record names its last refresh" in teaching
    assert "never report a landing you did not read" in teaching


def test_watcher_teaching_surfaces_name_the_split_not_a_blanket_ban():
    notes = _merge_recipe()["notes"]
    assert "A relay-launched session ignores --wait" in notes
    assert "only for a harness with a native idle-wake primitive" in notes
    assert "no or unverified idle wake get one foreground command" in notes
    assert "yoke github merge-queue readiness PREFIX-N --json" in notes
    assert "null arming with an entry means consumed" in notes
    # Phrases stay inside one source line: this reads the module text, where
    # adjacent string literals keep their quotes and escapes.
    epilog = _words(_read(WATCH_MERGE_SOURCE))
    assert "a native idle-wake primitive gets the" in epilog
    assert "with no or unverified idle wake, get the foreground" in epilog


def test_command_reference_conditions_any_later_completion_message():
    for path in (COMMAND_REFERENCE, BUNDLE_COMMAND_REFERENCE):
        content = _words(_read(path)).lower()
        assert "the shared selector reads the caller's manifest wake capability" in (
            content
        )
        assert "a native idle-wake primitive gets the background subscription" in (
            content
        )
        assert "no or unverified idle wake gets one foreground command" in content
        assert "rely on a later completion message only when" in content


def test_no_teaching_surface_still_carries_the_retired_blanket_prohibition():
    surfaces = (
        DASH_MERGE,
        USHER_MERGE,
        WORKER_LIFECYCLE,
        SKILLS / "steer" / "worker-launch.md",
        BUNDLE_SKILLS / "dash" / "merge.md",
        BUNDLE_SKILLS / "usher" / "merge.md",
        BUNDLE_SKILLS / "steer" / "worker-lifecycle.md",
        BUNDLE_SKILLS / "steer" / "worker-launch.md",
        COMMAND_REFERENCE,
        BUNDLE_COMMAND_REFERENCE,
        WATCH_MERGE_SOURCE,
        WATCHERS_PACKET_SOURCE,
    )
    for path in surfaces:
        content = _read(path)
        for retired in RETIRED_BLANKET_PROHIBITIONS:
            assert retired not in content, f"{path} still teaches {retired!r}"
        for retired in RETIRED_REACHABILITY_GATING:
            assert retired not in content, f"{path} still teaches {retired!r}"
