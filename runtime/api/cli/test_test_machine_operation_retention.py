"""Interactive retention finishes while submit has not released the host."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_cli.commands.adapters import test_machine_operation as adapter
from yoke_contracts.api.function_call import ActorContext, FunctionCallResponse
from yoke_harness import golden_snapshot_retention as retention


DESTINATION = "/goldens/tester-home-new"
CURRENT = "/goldens/tester-home-current"


@pytest.mark.parametrize("status", ["verified", "error"])
@pytest.mark.parametrize("keep_state", ["known", "missing", "unknown"])
def test_capture_retains_before_submit_stops_host(monkeypatch, status, keep_state):
    events = []
    stopped = False
    execution = {
        "project": "example", "settings": {"user": "tester"},
        "lease_id": 1, "contract_digest": "digest",
        "golden_destination": DESTINATION,
    }
    keep_fields = {
        "known": {"kept_golden_paths": [CURRENT, DESTINATION]},
        "missing": {},
        "unknown": {"kept_golden_paths_unknown": "another home is leased"},
    }[keep_state]

    def dispatch(*, function_id, **kwargs):
        nonlocal stopped
        phase = function_id.rsplit(".", 1)[1]
        events.append(phase)
        if phase == "begin":
            result = {"execution": execution, **keep_fields}
        elif phase == "submit":
            assert status == "error" or "retention" in events
            stopped = True
            result = {"status": status, "golden_baseline_path": DESTINATION}
        else:
            assert phase == "abort"
            stopped = True
            result = {"released": True}
        return FunctionCallResponse(
            success=True, function=function_id, version="v1", result=result,
        )

    def run(command, **kwargs):
        assert not stopped, "SSH contacted a host stopped after submit"
        events.append("ssh")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def retain(execution, destination, kept_paths):
        assert status == "verified"
        assert kept_paths == [CURRENT, DESTINATION]
        assert not stopped
        events.append("retention")
        return retention.apply_retention(
            run, destination=destination, user="tester", kept_paths=kept_paths,
        )

    monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(adapter, "build_actor", lambda **kwargs: ActorContext(actor_id="2", session_id="holder"))
    monkeypatch.setattr(adapter, "call_dispatcher", dispatch)
    monkeypatch.setattr(adapter, "_power", lambda: SimpleNamespace(power_on=lambda *a: None))
    monkeypatch.setattr(retention, "retain_registered_golden", retain)
    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        lambda *a, **kw: SimpleNamespace(
            payload={"status": status},
            cleanup_artifacts=lambda: events.append("cleanup"),
        ),
    )
    monkeypatch.setattr("yoke_harness.harness_cli_latest.warn_capture_behind_latest", lambda *a: None)
    emitted = []
    monkeypatch.setattr(adapter, "emit_response", lambda response, **kw: emitted.append(response) or 0)

    adapter._execute(
        operation="golden_capture", project="example", test_machine=None,
        baseline=None, destination=None, probes_document=None,
        session_id=None, json_mode=True,
    )

    assert events.count("cleanup") == 1
    if status == "error":
        assert events == ["begin", "submit", "cleanup"]
    elif keep_state == "known":
        assert events == ["begin", "retention", "ssh", "submit", "cleanup"]
        assert emitted[0].result["removed_snapshots"] == []
    else:
        assert events == ["begin", "cleanup", "abort"]
        assert emitted[0].error.code == "golden_snapshot_retention_failed"
        assert "server lease was released" in emitted[0].error.message
        if keep_state == "missing":
            assert "Serving floor: next-release" in emitted[0].error.message


def test_begin_keeps_leased_home_check(monkeypatch):
    from yoke_core.domain import machine_qa_golden_destination as golden
    from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError

    settings = {"os": "linux", "resource_name": "lab"}
    monkeypatch.setattr(golden, "shared_home_registrations", lambda *a: [])
    monkeypatch.setattr(golden, "leased_shared_home", lambda *a, **kw: "other home leased")
    fields = golden.kept_golden_fields(None, settings=settings, destination=DESTINATION)
    assert fields == {"kept_golden_paths_unknown": "other home leased"}

    def unreadable(*args):
        raise TestMachineCapabilityError("unreadable registration")

    monkeypatch.setattr(golden, "shared_home_registrations", unreadable)
    fields = golden.kept_golden_fields(None, settings=settings, destination=DESTINATION)
    assert "unreadable registration" in fields["kept_golden_paths_unknown"]
