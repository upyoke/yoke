"""Dash survey relay timeout recovery and response rendering."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

from yoke_cli.commands import _helpers
from yoke_cli.commands.adapters import (
    conflict_survey_status,
    dash,
    dash_survey_recovery,
    lane_tree,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.conflict_survey import DURABLE_ABSENT, DURABLE_RECORDED


def _transport_failure() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="direct_workflow.dash.survey",
        version="v1",
        error=FunctionError(
            code="https_transport_failed",
            message="relay deadline exceeded",
        ),
    )


def _status_response(
    state: str, *, path: str = "pkg/change.py", no_changes: bool = False,
):
    recorded = state == DURABLE_RECORDED
    return FunctionCallResponse(
        success=True,
        function="direct_workflow.conflict_survey.status",
        version="v1",
        result={
            "item_id": 9,
            "workflow_id": "dash",
            "durable_state": state,
            "found": recorded,
            "clear": recorded,
            "touch_paths": [path] if recorded and not no_changes else [],
            "integration_target": "main",
            "fingerprint": "durable-fingerprint" if recorded else "",
            "observed_at": "2026-08-19T12:00:00Z" if recorded else "",
            "blockers": [],
            "no_changes": no_changes,
        },
    )


def _run_survey(monkeypatch, capsys, status_response):
    size = {
        "path": "pkg/change.py",
        "current_line_count": 12,
        "remaining_headroom": 338,
        "at_or_over_limit": False,
        "limit": 350,
        "classification": "authored",
    }
    monkeypatch.setattr(
        dash,
        "item_lane_tree",
        lambda *a, **k: lane_tree.LaneTree(),
    )
    monkeypatch.setattr(dash, "survey_path_sizes", lambda *a, **k: [size])
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        _helpers,
        "build_actor",
        lambda session_id: ActorContext(actor_id="op", session_id=session_id),
    )
    monkeypatch.setattr(_helpers, "call_dispatcher", lambda **_: _transport_failure())
    status_calls = []

    def _status(**kwargs):
        status_calls.append(kwargs)
        return status_response

    monkeypatch.setattr(dash_survey_recovery, "call_dispatcher", _status)
    rc = dash.dash_survey(
        [
            "YOK-9",
            "--path",
            "pkg/change.py",
            "--session-id",
            "session",
            "--json",
        ]
    )
    return rc, json.loads(capsys.readouterr().out), status_calls


def test_timeout_recovers_matching_durable_survey_and_renders_json(
    monkeypatch,
    capsys,
):
    rc, emitted, status_calls = _run_survey(
        monkeypatch,
        capsys,
        _status_response(DURABLE_RECORDED),
    )

    assert rc == 0
    assert emitted["success"] is True
    assert emitted["result"]["recovered_from_durable_state"] is True
    assert emitted["result"]["touch_paths"] == ["pkg/change.py"]
    assert emitted["warnings"][0]["code"] == "survey_timeout_recovery"
    assert status_calls[0]["function_id"] == ("direct_workflow.conflict_survey.status")


def test_timeout_with_absent_row_renders_a_durable_state_error(
    monkeypatch,
    capsys,
):
    rc, emitted, status_calls = _run_survey(
        monkeypatch,
        capsys,
        _status_response(DURABLE_ABSENT),
    )

    assert rc == 1
    assert emitted["success"] is False
    assert emitted["error"]["code"] == "https_transport_failed"
    assert "durable survey state is absent" in emitted["error"]["message"]
    assert len(status_calls) == 1


def test_timeout_recovers_matching_explicit_no_change_survey(monkeypatch):
    monkeypatch.setattr(
        dash_survey_recovery, "call_dispatcher",
        lambda **_kwargs: _status_response(DURABLE_RECORDED, no_changes=True),
    )
    recover = dash_survey_recovery.build_survey_timeout_recovery(
        TargetRef(kind="item", item_id=9),
        {"paths": [], "path_sizes": [], "integration_target": "main",
         "no_changes": True},
    )

    response = recover(
        _transport_failure(),
        ActorContext(actor_id="op", session_id="session"),
    )

    assert response.success is True
    assert response.result["touch_paths"] == []
    assert response.result["no_changes"] is True


def test_status_human_output_names_absence(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(conflict_survey_status, "dispatch_and_emit", _dispatch)
    assert conflict_survey_status.conflict_survey_status(["YOK-9"]) == 0
    stdout = io.StringIO()
    captured["human_writer"](
        SimpleNamespace(result={"durable_state": DURABLE_ABSENT}),
        stdout,
        io.StringIO(),
    )
    assert stdout.getvalue() == "survey-absent\n"
