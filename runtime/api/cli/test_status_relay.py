"""`yoke status` reports a dead relay as down, never ok."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import status_relay
from yoke_contracts.machine_config import relay_instance, runtime

MACHINE = "m-1"


@pytest.fixture(autouse=True)
def _instance(monkeypatch):
    instance = SimpleNamespace(environment="prod")
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", lambda **kw: instance)
    monkeypatch.setattr(runtime, "machine_id", lambda path: MACHINE)
    monkeypatch.setattr(status_relay.sys, "platform", "win32")
    return instance


def _report(reachable=True):
    return {"ok": True, "issues": [], "server": {"reachable": reachable}}


def _service(loaded=True, installed=True, supported=True):
    status = SimpleNamespace(supported=supported, loaded=loaded, reason="")
    return lambda instance: (status, installed)


def _rows(*rows):
    return lambda: list(rows)


def _connected(machine=MACHINE, liveness="connected"):
    return {"machine_id": machine, "liveness": liveness, "last_seen_at": "2026-11-21T13:00:00Z"}


def _attach(report, **kw):
    return status_relay.attach_relay(report, Path("/cfg.json"), **kw)


def test_running_relay_with_current_heartbeat_is_ok():
    report = _attach(_report(), service_status=_service(), relay_rows=_rows(_connected()))
    assert report["ok"] is True and report["issues"] == []
    assert report["relay"]["ok"] is True
    assert report["relay"]["last_seen_at"] == "2026-11-21T13:00:00Z"


def test_stopped_task_is_down_with_the_restart_recovery():
    report = _attach(_report(), service_status=_service(loaded=False), relay_rows=_rows())
    assert report["ok"] is False and report["relay"]["ok"] is False
    (issue,) = report["issues"]
    assert issue["code"] == status_relay.RELAY_DOWN and issue["severity"] == "error"
    assert "supervisor is not running it" in issue["message"]
    assert "no current heartbeat" in issue["message"]
    assert "`yoke relay install` to restart its Task Scheduler task" in issue["hint"]


def test_running_task_with_stale_heartbeat_is_down():
    stale = _rows(_connected(liveness="stale"), _connected(machine="other"))
    report = _attach(_report(), service_status=_service(), relay_rows=stale)
    assert report["ok"] is False
    (issue,) = report["issues"]
    assert issue["message"].endswith("the control plane has no current heartbeat from this machine")
    assert "restarts an exited relay within about a minute" in issue["hint"]


def test_unreachable_plane_still_reports_a_stopped_relay_but_not_a_stale_one():
    report = _attach(_report(reachable=False), service_status=_service(), relay_rows=_rows())
    assert report["ok"] is True and report["relay"]["ok"] is None
    assert report["relay"]["heartbeat_current"] is None
    report = _attach(_report(reachable=False), service_status=_service(loaded=False), relay_rows=_rows())
    assert report["ok"] is False and report["issues"][0]["code"] == status_relay.RELAY_DOWN


def test_unread_heartbeat_is_unknown_not_down():
    def fail():
        raise TimeoutError("plane timed out")
    report = _attach(_report(), service_status=_service(), relay_rows=fail)
    assert report["ok"] is True and report["relay"]["heartbeat_current"] is None
    assert "plane timed out" in report["relay"]["heartbeat_reason"]


@pytest.mark.parametrize("service", [_service(installed=False), _service(supported=False)])
def test_uninstalled_or_unsupported_relay_is_not_judged(service):
    report = _attach(_report(), service_status=service, relay_rows=_rows())
    assert report["ok"] is True and report["issues"] == []
    assert report["relay"]["ok"] is None


def test_unreadable_supervisor_is_reported_not_judged():
    def fail(instance):
        raise RuntimeError("schtasks missing")
    report = _attach(_report(), service_status=fail, relay_rows=_rows())
    assert report["ok"] is True and "schtasks missing" in report["relay"]["reason"]


def test_connection_without_a_relay_is_not_relevant(monkeypatch):
    def refuse(**kw):
        raise relay_instance.RelayInstanceError("no relay for this connection")
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", refuse)
    report = _attach(_report(), service_status=_service(), relay_rows=_rows())
    assert report["relay"] == {"relevant": False, "reason": "no relay for this connection"}
