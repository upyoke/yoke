"""`yoke status` reports a dead relay as down, never ok, without importing the engine."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import status_relay
from yoke_contracts.machine_config import relay_instance, runtime

_REAL_SERVICE_INSTALLED = status_relay._service_installed

MACHINE = "m-1"
STATE = Path("/home/u/.yoke/relays/abc")


@pytest.fixture(autouse=True)
def _instance(monkeypatch):
    instance = SimpleNamespace(environment="prod", state_dir=STATE, follows_served_release=True)
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", lambda **kw: instance)
    monkeypatch.setattr(runtime, "machine_id", lambda path: MACHINE)
    monkeypatch.setattr(status_relay.sys, "platform", "win32")
    return instance


def _report(reachable=True):
    return {"ok": True, "issues": [], "server": {"reachable": reachable}}


def _process(*cmdline, pid=4242):
    return SimpleNamespace(pid=pid, cmdline=tuple(map(str, cmdline)))


RUNNER = _process(STATE / "runtime/Scripts/pythonw.exe", "-I", STATE / "task-runner.py", pid=10)
RELAY = _process(STATE / "runtime/Scripts/python.exe", "-I", STATE / "runtime/Scripts/yoke.py", "relay", "serve")


def _procs(*processes):
    return lambda: list(processes)


def _rows(*rows):
    return lambda: list(rows)


def _row(machine=MACHINE, liveness="connected"):
    return {"machine_id": machine, "liveness": liveness, "last_seen_at": "2026-11-21T13:00:00Z"}


def _attach(report, **kw):
    return status_relay.attach_relay(report, Path("/cfg.json"), **kw)


def test_running_relay_with_current_heartbeat_is_ok():
    report = _attach(_report(), processes=_procs(RUNNER, RELAY), relay_rows=_rows(_row()))
    assert report["ok"] is True and report["issues"] == []
    assert report["relay"]["ok"] is True and report["relay"]["running"] is True
    assert report["relay"]["last_seen_at"] == "2026-11-21T13:00:00Z"


def test_ended_relay_is_down_even_while_its_heartbeat_lease_lasts():
    # The task runner is alive and about to restart the relay; the relay is not.
    report = _attach(_report(), processes=_procs(RUNNER), relay_rows=_rows(_row()))
    assert report["ok"] is False and report["relay"]["ok"] is False
    (issue,) = report["issues"]
    assert issue["code"] == status_relay.RELAY_DOWN and issue["severity"] == "error"
    assert issue["message"] == (
        "the machine relay (prod) is down: no relay process is running from its state directory"
    )
    assert "task runner restarts the relay within about a minute" in issue["hint"]
    assert "`yoke relay install`" in issue["hint"]


def test_stopped_relay_with_silent_heartbeat_names_both():
    stale = _rows(_row(liveness="silent"), _row(machine="other"))
    report = _attach(_report(), processes=_procs(), relay_rows=stale)
    (issue,) = report["issues"]
    assert "no relay process is running" in issue["message"]
    assert issue["message"].endswith("the control plane has no current heartbeat from this machine")


def test_running_relay_with_stale_heartbeat_is_down():
    report = _attach(_report(), processes=_procs(RELAY), relay_rows=_rows(_row(liveness="silent")))
    assert report["ok"] is False
    assert "restarts it within about a minute" in report["issues"][0]["hint"]


def test_unreachable_plane_still_reports_a_dead_relay_it_cannot_prove_installed_as_unknown():
    report = _attach(_report(reachable=False), processes=_procs(RELAY), relay_rows=_rows())
    assert report["ok"] is True and report["relay"]["ok"] is None
    assert report["relay"]["heartbeat_current"] is None
    report = _attach(_report(reachable=False), processes=_procs(), relay_rows=_rows())
    assert report["ok"] is True and report["relay"]["ok"] is None


def test_unread_heartbeat_is_unknown_not_down():
    def fail():
        raise TimeoutError("plane timed out")
    report = _attach(_report(), processes=_procs(RELAY), relay_rows=fail)
    assert report["ok"] is True and report["relay"]["heartbeat_current"] is None
    assert "plane timed out" in report["relay"]["heartbeat_reason"]


def test_machine_with_no_registered_relay_and_no_process_is_not_judged():
    report = _attach(_report(), processes=_procs(), relay_rows=_rows(_row(machine="other")))
    assert report["ok"] is True and report["issues"] == []
    assert report["relay"]["ok"] is None


def test_local_universe_relay_is_judged_by_its_heartbeat(_instance):
    _instance.follows_served_release = False
    report = _attach(_report(), processes=_procs(), relay_rows=_rows(_row()))
    assert report["ok"] is True and report["relay"]["running"] is None
    report = _attach(_report(), processes=_procs(), relay_rows=_rows(_row(liveness="silent")))
    assert report["ok"] is False


def test_installed_relay_that_is_not_running_is_down_even_when_the_plane_lists_none(monkeypatch):
    # windows-native-lab, signed out: the task is installed, no relay runs, and
    # the relay list showed no row for this machine.
    monkeypatch.setattr(status_relay, "_service_installed", lambda instance: True)
    for reachable in (True, False):
        report = _attach(_report(reachable=reachable), processes=_procs(), relay_rows=_rows())
        assert report["ok"] is False and report["relay"]["installed"] is True
        (issue,) = report["issues"]
        assert issue["message"].endswith("no relay process is running from its state directory")


@pytest.mark.parametrize("platform, relative", [
    ("win32", None),
    ("darwin", "Library/LaunchAgents/com.upyoke.relay.abc.plist"),
    ("linux", ".config/systemd/user/com.upyoke.relay.abc.service"),
])
def test_service_document_proves_installation(tmp_path, monkeypatch, platform, relative):
    monkeypatch.setattr(status_relay.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    instance = SimpleNamespace(label="com.upyoke.relay.abc", state_dir=tmp_path / "state")
    target = instance.state_dir / "task-runner.py" if relative is None else tmp_path / relative
    assert _REAL_SERVICE_INSTALLED(instance) is False
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")
    assert _REAL_SERVICE_INSTALLED(instance) is True


def test_connection_without_a_relay_is_not_relevant(monkeypatch):
    def refuse(**kw):
        raise relay_instance.RelayInstanceError("no relay for this connection")
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", refuse)
    report = _attach(_report(), processes=_procs(), relay_rows=_rows())
    assert report["relay"] == {"relevant": False, "reason": "no relay for this connection"}


def test_status_relay_never_imports_the_engine():
    tree = ast.parse(Path(status_relay.__file__).read_text(encoding="utf-8"))
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [name for name in modules if name.split(".")[0] == "yoke_core"]
    assert "importlib" not in modules
