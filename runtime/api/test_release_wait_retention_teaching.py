"""Every surface that teaches the close agrees on where a Dash leg ends.

A worker's legs end when its item reaches a terminal status, not when its
branch merges. The composed mandate, the Dash close-out phase, and the
steerer's worker-lifecycle rules must agree: a release wait keeps the claim
and parks, and the claim is released only at a terminal status.
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
    assert "A release wait retains the claim and park" in _mandate()
    teaching = _words(RELEASE_WAIT_RETENTION_TEACHING)
    assert "Do NOT release the claim and do NOT end your session there" in teaching
    assert "Any prompt that wakes you CLEARS that park" in teaching
    assert "re-park before stopping" in teaching


def test_the_worker_lifecycle_keeps_a_quiet_holder_through_delivery():
    collapsed = _words(_read(WORKER_LIFECYCLE))
    assert "the holder keeps its claim through delivery QA" in collapsed
    assert "Message a quiet worker first." in collapsed
    assert "Terminate only an unresponsive worker" in collapsed


def test_the_dash_close_out_stops_teaching_a_release_wait_release():
    content = _read(DASH_CLOSE_OUT)
    assert "yoke sessions touch --mode parked" in content
    collapsed = _words(content)
    assert "keep the claim and lane, send no DONE, and park whenever quiet" in (
        collapsed
    )
    assert "--stage STAGE --member PREFIX-N" in collapsed
    assert "At a terminal status: report to `yoke say --steering`, then release" in (
        collapsed
    )


def test_the_close_out_park_recipe_is_the_reason_the_product_stamps():
    """The recipe an owner types by hand when the stamp was unconfirmed has
    to be the same wait the close-out would have recorded."""
    assert park_reason("ITEM") in _read(DASH_CLOSE_OUT)


def test_the_install_bundle_copies_teach_the_same_retention():
    for relative in (
        "dash/close-out.md",
        "steer/worker-lifecycle.md",
        "steer/worker-launch.md",
    ):
        packaged = _read(BUNDLE / relative)
        assert packaged == _read(SKILLS / relative), relative
