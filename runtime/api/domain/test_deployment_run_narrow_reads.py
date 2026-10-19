"""Pin and ordinary run reads never walk member completion prerequisites."""

from unittest.mock import Mock

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_run_success_member_settlement import _executing_run
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.steering_fleet_test_helpers import NOW
from yoke_cli.commands.adapters import deployment_pin_guard
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain import deployment_run_completion_preview as completion
from yoke_core.domain.handlers.deployment_run_get import handle_deployment_run_get

RUN = "run-narrow-read"


def test_settling_run_pin_and_full_get_skip_many_member_requirements(
    test_db, monkeypatch
):
    _project(test_db)
    members = tuple(range(9901, 9925))
    for item_id in members:
        _ready_member(test_db, item_id, f"holder-{item_id}")
        for _ in range(8):
            insert_qa_requirement(test_db, item_id=item_id, qa_phase="verification")
    _executing_run(test_db, RUN, members)
    lineage = "a" * 40
    test_db.execute(
        "UPDATE deployment_runs SET settling_at=%s,release_lineage=%s WHERE id=%s",
        (NOW, lineage, RUN),
    )
    test_db.commit()
    diagnostic = Mock(
        side_effect=AssertionError("pin/full get must not compose closure")
    )
    monkeypatch.setattr(completion, "run_completion_diagnostics", diagnostic)
    calls = []

    def dispatch(*, function_id, target, payload):
        assert function_id == "deployment_runs.get"
        calls.append(payload)
        outcome = handle_deployment_run_get(
            deployment_request(
                function=function_id,
                target=target,
                payload=payload,
            )
        )
        assert outcome.primary_success, outcome.error
        return FunctionCallResponse(
            success=True,
            function=function_id,
            version="v1",
            result=outcome.result_payload,
        )

    monkeypatch.setattr(control_plane, "call_dispatcher", dispatch)
    pin = control_plane.run_pin(RUN)
    assert pin["release_lineage"] == lineage and pin["project"]
    assert calls == [{"field": "project"}, {"field": "release_lineage"}]
    result = dispatch(
        function_id="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
        payload={},
    )
    assert result.result["run"]["status"] == "executing"
    assert test_db.execute(
        "SELECT settling_at FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert "member_closure" not in result.result
    diagnostic.assert_not_called()


def test_member_closure_is_explicit_and_preserves_the_diagnostic(monkeypatch):
    diagnostic = {"members": [{"item_id": 7, "state": "blocked"}], "blocked": True}
    read = Mock(return_value=diagnostic)
    monkeypatch.setattr(completion, "run_completion_diagnostics", read)
    from yoke_core.domain import deployment_runs_crud_query

    monkeypatch.setattr(deployment_runs_crud_query, "get_run", lambda _: {"id": RUN})
    outcome = handle_deployment_run_get(
        deployment_request(
            function="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
            payload={"include_member_closure": True},
        )
    )
    assert outcome.primary_success
    assert outcome.result_payload["member_closure"] == diagnostic
    read.assert_called_once_with(RUN)


def test_retry_lineage_deadline_refuses_instead_of_skipping_the_guard(monkeypatch):
    def dispatch(**kwargs):
        assert kwargs["payload"] == {"field": "release_lineage"}
        return FunctionCallResponse(
            success=False,
            function="deployment_runs.get",
            version="v1",
            error=FunctionError(code="read_deadline_exceeded", message="slow read"),
        )

    monkeypatch.setattr(deployment_pin_guard, "call_dispatcher", dispatch)
    monkeypatch.setattr(deployment_pin_guard, "build_actor", lambda **_: None)
    with pytest.raises(
        deployment_pin_guard.PinRegressionError, match="read_deadline_exceeded"
    ) as raised:
        deployment_pin_guard._retry_run_lineage(RUN, None)
    assert f"yoke deployment-runs get {RUN} release_lineage" in str(raised.value)


def test_cli_requests_closure_only_when_explicit():
    from runtime.api.cli.test_yoke_operations_cli_deployment import (
        _run_capture,
        _stub_ok,
        _CAPTURED_REQUESTS,
    )

    rc, _, _ = _run_capture(
        _stub_ok, "deployment-runs", "get", RUN, "--include-member-closure"
    )
    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].payload == {
        "field": None,
        "include_member_closure": True,
    }


def test_watcher_captures_a_pin_read_deadline(monkeypatch, tmp_path, capsys):
    from contextlib import nullcontext
    from yoke_core.tools import watch_deploy
    from yoke_core.domain.deploy_pipeline_driver_client import DriverLivenessPump

    monkeypatch.setattr(watch_deploy, "_hold_driver", lambda *a, **k: None)
    monkeypatch.setattr(watch_deploy, "_drop_driver", lambda *a, **k: None)
    monkeypatch.setattr(watch_deploy, "execution_connection_error", lambda _: None)
    monkeypatch.setattr(DriverLivenessPump, "running", lambda _: nullcontext())
    raw, progress = tmp_path / "raw.log", tmp_path / "progress.log"
    monkeypatch.setattr(
        watch_deploy._watch_runner, "bind_capture_paths", lambda *a: (raw, progress)
    )

    def refuse(*args):
        raise control_plane.DeploymentControlPlaneError(
            "slow composition; Recovery: use narrow field reads",
            code="read_deadline_exceeded",
        )

    monkeypatch.setattr(watch_deploy, "prepare_driver", refuse)
    assert watch_deploy.main([RUN]) == 2
    for output in (capsys.readouterr().err, raw.read_text(), progress.read_text()):
        assert "read_deadline_exceeded" in output
        assert "narrow field reads" in output and "Traceback" not in output
    assert "# watch_deploy exit=2" in progress.read_text()


@pytest.mark.parametrize(
    "fields",
    [["status", "release_lineage"], ["project", "target_environment", "status"]],
)
def test_multi_field_get_selects_only_named_columns(test_db, fields):
    _project(test_db)
    _executing_run(test_db, RUN, ())
    outcome = handle_deployment_run_get(
        deployment_request(
            function="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
            payload={"fields": fields},
        )
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["fields"] == fields
    assert set(outcome.result_payload["run"]) == set(fields)
    assert outcome.result_payload["run"]["status"] == "executing"
    assert "member_closure" not in outcome.result_payload


@pytest.mark.parametrize(
    "payload",
    [
        {"fields": []},
        {"fields": "status"},
        {"fields": [3]},
        {"fields": ["status"], "field": "project"},
        {"fields": ["status"], "include_member_closure": True},
        {"fields": ["status", "no_such_field"]},
    ],
)
def test_multi_field_get_refuses_invalid_selection(payload):
    outcome = handle_deployment_run_get(
        deployment_request(
            function="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
            payload=payload,
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code in {"payload_invalid", "invalid_field"}
    assert outcome.error.jsonpath == "$.payload.fields"
