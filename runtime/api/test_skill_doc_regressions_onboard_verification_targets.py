"""Shipped onboard and public QA docs match their canonical sources."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ONBOARD = REPO / ".agents/skills/yoke/onboard/verification-binding.md"
PUBLIC_QA = REPO / "docs/public/verification/index.md"
QA_MIRRORS = (
    REPO / ".yoke/docs/verification/index.md",
    REPO
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/docs/public/verification/index.md",
)
ONBOARD_MIRROR = (
    REPO
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke/"
    / "onboard/verification-binding.md"
)


def test_shipped_qa_and_onboard_docs_match_the_canonical_sources() -> None:
    public_text = PUBLIC_QA.read_bytes()
    assert all(path.read_bytes() == public_text for path in QA_MIRRORS)
    assert ONBOARD_MIRROR.read_bytes() == ONBOARD.read_bytes()
