"""Argument parsing, environment boundaries, and phase-event failures."""

from types import SimpleNamespace
from typing import Any, Dict
from unittest import mock

import pytest

from yoke_core.engines import advance_implementation_entry as orch


def test_parse_item_argument_accepts_typed_internal_id():
    assert orch._parse_item_argument(1730) == 1730


def test_parse_item_id_prefix_ref_resolves_project_sequence(test_db):
    """``PREFIX-N`` maps to the item's project sequence, not the internal id."""
    from runtime.api.fixtures.backlog import insert_item

    # Internal id 500 carries public ref YOK-444; a prefix-strip resolver
    # would return 444.
    insert_item(test_db, id=500, title="t", project="yoke", project_sequence=444)
    test_db.commit()
    assert orch._parse_item_argument("YOK-444") == 500
    assert orch._parse_item_argument(" yok-444 ") == 500


def test_parse_item_id_invalid_raises():
    with pytest.raises(ValueError):
        orch._parse_item_argument("not-a-number")


@pytest.mark.parametrize(
    "item_in,capability,want_outcome",
    [
        ({}, False, "skipped:no-project"),
        ({"project": "yoke"}, False, "skipped:no-capability"),
    ],
)
def test_environment_phase_skip_branches(item_in, capability, want_outcome):
    """Capable-project provisioning is exercised end-to-end in
    test_advance_implementation_entry_cross_project; here we only assert the
    two skip branches stay on the orchestrator shim."""
    with mock.patch(
        "yoke_core.domain.projects_crud.cmd_has_capability",
        return_value=capability,
    ):
        outcome, _ctx = orch._run_environment_phase(item_in, "sess")
    assert outcome == want_outcome


def test_record_phase_fails_closed_when_event_not_written(monkeypatch):
    monkeypatch.setattr(
        orch, "emit_event", lambda *a, **k: SimpleNamespace(ok=False, reason="x")
    )
    summary = {"phases": []}
    with pytest.raises(RuntimeError, match="AdvancePhaseCompleted"):
        orch._record_phase(
            summary,
            item_id=42,
            phase="preflight",
            outcome="completed",
            duration_ms=1,
            session_id="s1",
        )
    assert summary["phases"] == []


def test_main_delegates_to_run(monkeypatch):
    calls: Dict[str, Any] = {}

    def fake_run(item_id, **kwargs):
        calls["item_id"] = item_id
        calls.update(kwargs)
        return 0

    monkeypatch.setattr(orch, "run", fake_run)
    assert (
        orch.main(
            [
                "--item",
                "YOK-42",
                "--no-worktree",
                "--force",
                "--qa-bypass",
                "--session-id",
                "manual-id",
            ]
        )
        == 0
    )
    assert calls["item_id"] == "YOK-42"
    assert calls["no_worktree"] and calls["force"] and calls["qa_bypass"]
    assert calls["session_id"] == "manual-id"


def test_main_surfaces_unexpected_exception(monkeypatch, capsys):
    monkeypatch.setattr(
        orch,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert orch.main(["--item", "YOK-1"]) == 1
    assert "orchestrator crashed" in capsys.readouterr().err
