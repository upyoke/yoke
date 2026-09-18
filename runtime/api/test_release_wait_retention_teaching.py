"""Every surface that teaches the close agrees on where a Dash leg ends.

A worker's legs end when its item reaches a terminal status, not when its
branch merges. Three surfaces had to say so together — the composed mandate,
the Dash close-out phase, and the steerer's worker-lifecycle rules — because
the failure was one of them contradicting the others: the mandate said report
and END, the close-out offered a claim release, and the item at its release
wait ended up with no owner at all.

These assert the doc copies carry the composed teaching verbatim, matching
how the landing-handoff teaching is already pinned, so a reworded constant
cannot drift away from the prose a worker reads.
"""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read
from yoke_core.domain.release_wait_ownership import (
    RELEASE_WAIT_RETENTION_TEACHING,
    park_reason,
)
from yoke_core.domain.session_launch_mandate import compose_single_item_mandate
from yoke_core.domain.session_launch_mandate_teaching import STANDING_TEACHINGS

DASH_CLOSE_OUT = SKILLS / "dash" / "close-out.md"
WORKER_LIFECYCLE = SKILLS / "steer" / "worker-lifecycle.md"
BUNDLE = (
    REPO
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".agents"
    / "skills"
    / "yoke"
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


def test_the_retention_teaching_is_one_of_the_standing_mandate_paragraphs():
    assert RELEASE_WAIT_RETENTION_TEACHING in STANDING_TEACHINGS
    assert RELEASE_WAIT_RETENTION_TEACHING in _mandate()


def test_the_worker_lifecycle_copy_matches_the_composed_teaching():
    content = _read(WORKER_LIFECYCLE)
    assert RELEASE_WAIT_RETENTION_TEACHING in content
    collapsed = _words(content)
    assert "the worker stays the owner through delivery" in collapsed
    assert "do not terminate it for being quiet" in collapsed
    assert "A holder that goes quiet WITHOUT that park is treated as gone" in (
        collapsed
    )
    assert "expected to re-park before it goes quiet again" in collapsed


def test_the_dash_close_out_stops_teaching_a_release_wait_release():
    content = _read(DASH_CLOSE_OUT)
    assert "yoke sessions touch --mode parked" in content
    collapsed = _words(content)
    assert "You stay the owner through delivery." in collapsed
    assert "Do not release the claim and do not end the session there" in collapsed
    assert "skip it entirely while the item sits at a release wait" in collapsed
    assert "owes no terminal report yet" in collapsed
    # The two corrections the review caught: a wake clears the park, and the
    # spare that protects a declared wait is bounded rather than forever.
    assert "Any prompt that wakes you clears the park" in collapsed
    assert "re-park first with the command above" in collapsed
    assert "only while the session holds nothing else" in collapsed
    assert "handed to steering by name" in collapsed
    # Only the run that discharges THIS item's delivery calls its owner.
    assert "a stage run in a stage-and-production pair will not call you" in (
        collapsed
    )


def test_the_close_out_park_recipe_is_the_reason_the_product_stamps():
    """The recipe an owner types by hand when the stamp was unconfirmed has
    to be the same wait the close-out would have recorded."""
    assert park_reason("ITEM") in _read(DASH_CLOSE_OUT)


def test_the_install_bundle_copies_teach_the_same_retention():
    for relative in ("dash/close-out.md", "steer/worker-lifecycle.md"):
        packaged = _read(BUNDLE / relative)
        assert packaged == _read(SKILLS / relative), relative
