"""Blitz close teaching walks declared stages and retains terminal gates."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import workflow_declared_transitions as declared
from yoke_core.domain.blitz_document_archive import BLITZ_DOCUMENT_ARCHIVE_FAILURE
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
from runtime.api.skill_doc_regressions_test_helpers import _read_skill_corpus


ROOT = Path(__file__).parents[2]
BLITZ = ROOT / ".agents" / "skills" / "yoke" / "blitz"
HELP = ROOT / ".agents" / "skills" / "yoke" / "help" / "SKILL.md"
WORKFLOWS = ROOT / "docs" / "public" / "workflows.md"
ARCHIVE = (
    ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "domain"
    / "blitz_document_archive.py"
)


def test_blitz_10_refuses_reviewing_implementation_to_done() -> None:
    workflow = builtin_workflow_runtime("blitz")
    refusal = declared.undeclared_forward_transition(
        workflow,
        from_stage_id="reviewing-implementation",
        to_stage_id="done",
    )

    assert workflow.version == 10
    assert "declares no transition" in refusal
    assert "reviewing-implementation" in refusal
    assert declared.declared_next_stage_ids(workflow, "reviewing-implementation") == (
        "release",
    )
    assert declared.declares_transition(workflow, "release", "done")


def test_blitz_docs_do_not_name_the_missing_close_transition() -> None:
    corpus = _read_skill_corpus(BLITZ)
    help_text = HELP.read_text()
    workflows = WORKFLOWS.read_text()

    assert "--from reviewing-implementation --to done" not in corpus
    assert "reviewing-implementation -> done" not in corpus
    assert "reviewing-implementation → done" not in corpus
    close = (BLITZ / "review-and-complete.md").read_text()
    assert "--from LIVE_STAGE --to NEXT_STAGE" in close
    assert "yoke workflows item get ITEM --json" in close
    assert "yoke workflows version get WORKFLOW_ID WORKFLOW_VERSION --json" in close
    assert "definition.transitions" in close
    assert "definition.terminal_stage_ids" in close
    assert "`doc_completion`" in close
    assert "document-archive" in close
    assert "keep the work claim and park this session" in close
    assert "or `release`" in corpus
    assert "-> release -> done" in help_text
    assert "blitz → release → done" in workflows


def test_archive_recovery_retries_the_terminal_release_to_done_edge() -> None:
    text = ARCHIVE.read_text()

    assert BLITZ_DOCUMENT_ARCHIVE_FAILURE in text
    assert "retry the release -> done" in text
    assert "retry the reviewing-implementation -> done" not in text
