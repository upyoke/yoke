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
PREPARE_COMMAND = "yoke worktree prepare --item PREFIX-N --project {PROJECT}"


def _doc_text() -> str:
    return ACTIVATION_DOC.read_text(encoding="utf-8")


def test_prepares_registered_lanes_before_task_dispatch():
    text = _doc_text()
    dispatch = "yoke conduct epic-task update-status --epic PREFIX-N"
    assert PREPARE_COMMAND in text
    assert dispatch in text
    assert text.index(PREPARE_COMMAND) < text.index(dispatch)
    assert "python3 -m yoke_core.domain.worktree create" not in text
