"""Onboard and public QA docs teach the registered-command target matrix."""

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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_onboard_teaches_each_registered_command_target_mode() -> None:
    text = " ".join(_read(ONBOARD).split())
    retired_blanket_claim = "It needs no " + "environment"
    assert (
        "Deployed scopes take one target: `--environment` or `--requires-base-url`; "
        "`quick`/`full` take neither." in text
    )
    assert retired_blanket_claim not in text


def test_public_qa_doc_keeps_generic_and_registered_plan_contracts_distinct() -> None:
    text = _read(PUBLIC_QA)
    assert "project source · no deployment environment" in text
    assert "Generic `yoke qa plan" in text
    assert "create` remains environment-bound" in text
    assert "Exactly one local deployed target is required" in text


def test_shipped_qa_and_onboard_docs_match_the_canonical_sources() -> None:
    public_text = PUBLIC_QA.read_bytes()
    assert all(path.read_bytes() == public_text for path in QA_MIRRORS)
    assert ONBOARD_MIRROR.read_bytes() == ONBOARD.read_bytes()
