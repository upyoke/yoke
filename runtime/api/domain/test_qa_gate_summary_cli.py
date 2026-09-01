# ruff: noqa: F811
"""CLI coverage for the typed read-only QA gate summary."""

from __future__ import annotations

import json

from runtime.api.domain.qa_gate_summary_test_fixtures import (  # noqa: F401
    add_requirement,
    qa_db,
)
from yoke_core.domain.qa_gate_summary import cmd_gate_summary


def test_cli_target_validation(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=42,
        epic_id=None,
        task_num=None,
        target="invalid",
        as_json=False,
    )
    assert rc == 2
    assert "must be one of" in capsys.readouterr().err


def test_cli_target_requires_item_or_epic(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=None,
        epic_id=None,
        task_num=None,
        target="reviewed-implementation",
        as_json=False,
    )
    assert rc == 2
    assert "item-id" in capsys.readouterr().err


def test_cli_item_and_epic_are_mutually_exclusive(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=42,
        epic_id=833,
        task_num=5,
        target="reviewed-implementation",
        as_json=False,
    )
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_cli_json_output_is_valid_json(qa_db, capsys):
    add_requirement(qa_db, qa_kind="e2e")
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=42,
        epic_id=None,
        task_num=None,
        target="reviewed-implementation",
        as_json=True,
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["target"] == "YOK-42"
    assert parsed["transition"] == "reviewed-implementation"
    assert parsed["e2e_unsatisfied_count"] == 1


def test_cli_text_output_includes_status_and_counts(qa_db, capsys):
    add_requirement(qa_db, qa_kind="ac_verification")
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=42,
        epic_id=None,
        task_num=None,
        target="reviewed-implementation",
        as_json=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status: UNSATISFIED" in out
    assert "Blocking unsatisfied: 1" in out
    assert "ac_verification" in out


def test_cli_returns_zero_for_unsatisfied_diagnostic(qa_db, capsys):
    """Diagnostic reads exit zero even when the summary is unsatisfied."""
    rc = cmd_gate_summary(
        db_path=qa_db,
        item_id=999,
        epic_id=None,
        task_num=None,
        target="reviewed-implementation",
        as_json=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "No QA requirements" in out
