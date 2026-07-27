"""Usher Browser-method evidence regression coverage."""

from __future__ import annotations

from pathlib import Path


MERGE_DOC = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "yoke"
    / "usher"
    / "merge.md"
)


def _merge_text() -> str:
    assert MERGE_DOC.is_file()
    return MERGE_DOC.read_text(encoding="utf-8")


def test_pre_merge_skip_recognizes_passing_browser_method_cases() -> None:
    text = _merge_text()

    assert "qreq.method_id IN ('browser-check', 'browser-inspection')" in text
    assert "qreq.qa_phase = 'verification'" in text
    assert "qr.verdict = 'pass'" in text
    assert "Browser method cases" in text


def test_legacy_browser_kind_fallback_is_null_method_only() -> None:
    text = _merge_text()

    assert "method_id IS NULL branch is compatibility-only" in text
    assert (
        "OR (qreq.method_id IS NULL \\\n"
        " AND qreq.qa_kind IN ('browser_smoke', 'browser_diff')))" in text
    )
    assert text.count("browser_smoke") == 1
    assert text.count("browser_diff") == 1


def test_usher_drops_retired_browser_execution_recipes() -> None:
    text = _merge_text()

    assert "yoke qa browser run" not in text
    assert "--success-policy" not in text
    assert "--executor-type browser_substrate" not in text
