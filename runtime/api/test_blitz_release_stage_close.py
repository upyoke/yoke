"""Blitz close walks declared stages and retains terminal gates."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import workflow_declared_transitions as declared
from yoke_core.domain.blitz_document_archive import BLITZ_DOCUMENT_ARCHIVE_FAILURE
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


ROOT = Path(__file__).parents[2]
ARCHIVE = (
    ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "domain"
    / "blitz_document_archive.py"
)


def test_blitz_refuses_reviewing_implementation_to_done() -> None:
    workflow = builtin_workflow_runtime("blitz")
    refusal = declared.undeclared_forward_transition(
        workflow,
        from_stage_id="reviewing-implementation",
        to_stage_id="done",
    )

    assert "declares no transition" in refusal
    assert "reviewing-implementation" in refusal
    assert declared.declared_next_stage_ids(workflow, "reviewing-implementation") == (
        "release",
    )
    assert declared.declares_transition(workflow, "release", "done")


def test_archive_recovery_retries_the_terminal_release_to_done_edge() -> None:
    text = ARCHIVE.read_text()

    assert BLITZ_DOCUMENT_ARCHIVE_FAILURE in text
    assert "retry the release -> done" in text
    assert "retry the reviewing-implementation -> done" not in text
