"""Regression checks for canonical Browser method-case guidance."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO


BROWSER_SUBSTRATE = REPO / "docs" / "browser-substrate.md"
CASE_ORCHESTRATION = REPO / "docs" / "browser-substrate" / "scenario-orchestration.md"
CANDIDATE_VERIFICATION = REPO / ".agents" / "skills" / "yoke" / "dash" / "verify.md"
TIMING_PROFILE = REPO / ".test_durations"
BROWSER_METHOD_MODULES = (
    REPO / "packages/yoke-core/src/yoke_core/domain/browser_qa_requirement.py",
    REPO / "packages/yoke-core/src/yoke_core/domain/qa_browser_evidence_check.py",
    REPO / "packages/yoke-core/src/yoke_core/domain/qa_gate_helpers.py",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing canonical Browser QA document: {path}"
    return path.read_text(encoding="utf-8")


def test_browser_docs_link_candidate_verification() -> None:
    text = _read(BROWSER_SUBSTRATE) + _read(CASE_ORCHESTRATION)

    assert CANDIDATE_VERIFICATION.is_file()
    assert ".agents/skills/yoke/dash/verify.md" in text


def test_gate_recovery_names_the_registered_case_runners() -> None:
    text = _read(BROWSER_METHOD_MODULES[1])
    gates = (REPO / "packages/yoke-core/src/yoke_core/domain/qa_gates.py").read_text(
        encoding="utf-8"
    )
    for source in (text, gates):
        assert (
            "`yoke qa plan run --item {name} --transition {transition_name}`" in source
        )
        assert "`yoke qa case run --requirement-id <id>`" in source
        assert "retry the lifecycle transition" in source
        assert "/yoke " + "advance" not in source


def test_retired_browser_and_migration_residue_is_absent() -> None:
    browser_text = "\n".join(_read(path) for path in BROWSER_METHOD_MODULES)
    timing_text = _read(TIMING_PROFILE)

    assert "legacy Browser case" not in browser_text
    assert "test_harness_session_project_identity.py" not in timing_text
