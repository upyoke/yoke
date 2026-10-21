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
from yoke_core.domain.session_launch_mandate_teaching import STANDING_TEACHINGS

DASH_CLOSE_OUT = SKILLS / "dash" / "close-out.md"
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


def test_the_retention_teaching_is_one_of_the_standing_mandate_paragraphs():
    assert RELEASE_WAIT_RETENTION_TEACHING in STANDING_TEACHINGS


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
