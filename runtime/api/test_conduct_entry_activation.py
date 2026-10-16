"""Conduct prepares all registered lanes before reading task baselines.

The registered command owns runtime selection and shared preflight; activation
ordering is exercised by the unchanged shared preflight order test and the
Epic preparation route tests. Task baselines remain main-checkout branch reads
because the task's own claim has not yet been acquired.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVATION_DOC = (
    REPO_ROOT / ".agents/skills/yoke/conduct/entry-activation-resolution.md"
)
PREPARE_COMMAND = 'yoke worktree prepare --item "${_epic_ref}" --project "${PROJECT}"'


def _doc_text() -> str:
    return ACTIVATION_DOC.read_text(encoding="utf-8")


def test_prepares_registered_lanes_before_baseline_loop():
    text = _doc_text()
    baseline = 'git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}"'
    assert PREPARE_COMMAND in text
    assert baseline in text
    assert text.index(PREPARE_COMMAND) < text.index(baseline)
    assert "python3 -m yoke_core.domain.worktree create" not in text
    assert "before a lane exists" in text


def test_preparation_teaches_path_claim_activation_separately_from_lifecycle():
    text = _doc_text()
    assert "These are path-claim states, not item lifecycle statuses." in text
    assert "activates required claims" in text
    assert PREPARE_COMMAND in text
    assert "Yoke's installed interpreter" in text


def test_documents_idempotent_preparation():
    text = _doc_text()
    assert "idempotent" in text.lower()
    assert "correct existing branches" in text


def test_preparation_passes_project_for_cross_project_epics():
    assert PREPARE_COMMAND in _doc_text()
