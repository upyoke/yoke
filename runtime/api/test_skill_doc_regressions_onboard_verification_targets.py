"""Onboard and public QA docs teach the registered-command target matrix."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ONBOARD = REPO / ".agents/skills/yoke/onboard/hosting-and-environments.md"
PUBLIC_QA = REPO / "docs/public/qa.md"
QA_MIRRORS = (
    REPO / ".yoke/docs/qa.md",
    REPO / "packages/yoke-core/src/yoke_core/install_bundle_tree/docs/public/qa.md",
)
ONBOARD_MIRROR = (
    REPO
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke/"
    / "onboard/hosting-and-environments.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_onboard_teaches_each_registered_command_target_mode() -> None:
    text = _read(ONBOARD)
    assert "`quick` and `full` are project-targeted" in text
    assert "--environment {site}/{environment}" in text
    assert "--requires-base-url" in text
    assert "CI, `--environment` is required" in text
    assert "validates the combination before writing the plan" in text
    assert "It needs no environment" not in text


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
