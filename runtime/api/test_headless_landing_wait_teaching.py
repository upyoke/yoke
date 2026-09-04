"""A headless worker is taught to hold its turn on a merge-queue landing.

The enqueue-and-re-enter handoff needs a session that can be prompted
again on the landing-complete message. A launched worker is a headless
command that cannot be, so ending its pass on ``landing_pending=true``
leaves the branch landed and the item at ``reviewing-implementation``
with nobody to close it out. These tests hold every surface that teaches
the split — the Dash close-out steps, the usher merge step, the composed
worker mandate, the steering worker-lifecycle copy of it, the packet
recipe, and the watcher help — to naming both routes and all three ways
the in-turn wait ends: merged, stopped, and the poll budget running out.
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

# The blanket prohibition the in-turn wait replaces. A surface still
# carrying it tells a launched worker the one thing it must not do.
RETIRED_BLANKET_PROHIBITIONS = (
    "Claude must never pass `--wait`",
    "Claude never passes `--wait`",
    "Claude never blocks on --wait",
    "Claude must not pass merge-item --wait",
)


def _words(text: str) -> str:
    """Collapse wrapping so prose assertions do not depend on line breaks."""
    return " ".join(text.split())


def _mandate(*, steering_launched: bool) -> str:
    return compose_single_item_mandate(
        public_ref="YOK-12",
        entrypoint="/yoke dash YOK-12",
        remaining_legs="the Dash leg to its merge/evidence close",
        steering_launched=steering_launched,
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


def test_dash_close_out_routes_the_landing_by_whether_the_session_is_headless():
    content = _words(_read(DASH_CLOSE))
    assert "Two-call handoff — an operator-opened session." in content
    assert "In-turn wait — a launched worker." in content
    assert "headless command that cannot accept a later prompt" in content
    # Why the handoff cannot be the launched worker's route: the landing is
    # recorded from GitHub either way, so the cost is a seat's attention
    # rather than a lost merge — which is still a cost worth avoiding.
    assert "at `reviewing-implementation` with nobody to re-enter" in content
    assert "recoverable rather than lost" in content
    assert "costs a" in content and "steering seat's attention" in content
    # The wait and the independent point-in-time read both name the queue.
    assert (
        "yoke watch merge --print-streaming-pair merge-item -- ITEM --wait" in content
    )
    assert "yoke github merge-queue readiness ITEM --json" in content
    assert "queue-entry=AWAITING_CHECKS" in content
    assert "consumed and in flight, not cleared" in content
    assert "never hand-author a `gh` poll" in content
    assert "none of them is silence" in content


def test_dash_close_out_names_every_way_the_in_turn_wait_ends():
    wait = _read(DASH_CLOSE).split("**In-turn wait — a launched worker.**", 1)[1]
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
    # The bounded deadline parks with the state it read, and only then.
    deadline = _outcome(wait, "poll budget exhausted")
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
    assert "A session launched from a worker mandate cannot accept that later" in (
        content
    )
    assert "dash/verification-and-close.md" in content
    assert "Never block a bare foreground call on the full wait." in content


def test_every_launched_worker_mandate_carries_the_in_turn_landing_wait():
    """Origin decides the report route; being launched decides this one."""
    for steering_launched in (True, False):
        assert HEADLESS_LANDING_WAIT_TEACHING in _mandate(
            steering_launched=steering_launched
        )
    teaching = HEADLESS_LANDING_WAIT_TEACHING
    assert "headless command that cannot be prompted again" in teaching
    assert "do not end the pass on it" in teaching
    assert "pass --wait and hold the turn on the merge watcher wrapper" in teaching
    assert "Merged closes the item out in that same turn" in teaching
    assert "a stopped landing rebases, re-runs the verification gate" in teaching
    assert "only the poll budget running out ends the turn" in teaching
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
    assert "operator-opened" in notes
    assert "launched headless worker passes --wait" in notes
    assert "Never block a bare foreground call on the full wait." in notes
    assert (
        "yoke github merge-queue readiness PREFIX-N --json"
        in (_merge_recipe()["recipe"])
    )
    assert "null arming is consumed" in notes
    epilog = _words(_read(WATCH_MERGE_SOURCE))
    assert "launched headless workers pass --wait" in epilog


def test_no_teaching_surface_still_carries_the_retired_blanket_prohibition():
    surfaces = (
        DASH_CLOSE,
        USHER_MERGE,
        WORKER_LIFECYCLE,
        BUNDLE_SKILLS / "dash" / "verification-and-close.md",
        BUNDLE_SKILLS / "usher" / "merge.md",
        BUNDLE_SKILLS / "steer" / "worker-lifecycle.md",
        WATCH_MERGE_SOURCE,
        WATCHERS_PACKET_SOURCE,
    )
    for path in surfaces:
        content = _read(path)
        for retired in RETIRED_BLANKET_PROHIBITIONS:
            assert retired not in content, f"{path} still teaches {retired!r}"
