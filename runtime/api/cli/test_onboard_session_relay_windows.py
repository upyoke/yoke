"""Windows setup installs a per-user task and renders restriction recovery."""

import json
import subprocess

from yoke_cli.commands.adapters import doctor, doctor_install
from yoke_cli.config import onboard_session_relay as relay
from yoke_cli.config import onboard_session_relay_wait as relay_wait
from yoke_cli.config.onboard_report_render import render_human
from yoke_cli.commands.adapters.session_control_relay_output import relay_status_fields
from yoke_contracts.machine_config.relay_instance import WINDOWS_RELAY_LOGOUT_BEHAVIOR
import pytest
pytestmark = pytest.mark.windows

def test_windows_setup_plans_installs_and_describes_both_build_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(relay.sys, "platform", "win32")
    for local in (False, True):
        steps = relay.plan_steps(local_destination=local, config_path=tmp_path / "config.json", environment="selected")
        assert steps[0]["action"] == "install-session-relay-task"
        assert steps[1] == {"action": "run-session-relay-task", "target": "Task Scheduler"}
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1 if argv[3] == "status" else 0, "", "")
        outcome = relay.install(local_destination=local, environment="selected", runner=run, wait_for_connection=lambda _: True)
        assert outcome.installed and not outcome.reused
        assert calls[1][3:] == ["install", "--environment", "selected"]
        fragment = relay.report_fragment(planned=True, installed=True, local_destination=local,
                                         config_path=tmp_path / "config.json", environment="selected")
        assert "task" in fragment and "plist" not in fragment and "unit" not in fragment
        lines = relay.report_complete_lines(fragment)
        assert WINDOWS_RELAY_LOGOUT_BEHAVIOR in lines
        assert any("battery" in line for line in lines)


def test_windows_status_names_task_and_shows_policy_restriction():
    fields = dict(relay_status_fields({
        "task_name": "user-relay", "task_present": True, "task_current": False,
        "enabled": False, "loaded": False, "supported": False,
        "supervision_reason": "Task Scheduler denied by policy; permit interactive user tasks",
        "logout_behavior": WINDOWS_RELAY_LOGOUT_BEHAVIOR,
    }))
    assert fields["User service"] == "user-relay"
    assert fields["Configuration present"] and not fields["Configuration current"]
    assert not fields["Service loaded"] and not fields["Enabled at login"]
    assert "denied by policy" in fields["Supervision reason"]
    assert fields["Logout behavior"] == WINDOWS_RELAY_LOGOUT_BEHAVIOR


#: A manual first served-release install on native Windows took this long.
OBSERVED_FIRST_INSTALL_SECONDS = 349
#: A native Windows relay's first heartbeat came this long after it started.
OBSERVED_FIRST_HEARTBEAT_SECONDS = 116


def _installer(install_seconds, timeouts=None):
    """Status unsatisfied; install takes *install_seconds* against its bound."""
    def run(argv, **kwargs):
        if argv[3] == "status":
            return subprocess.CompletedProcess(argv, 1, "", "")
        if timeouts is not None:
            timeouts.append(kwargs["timeout"])
        if install_seconds > kwargs["timeout"]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, "", "")
    return run


def _waits(connected=True):
    calls = []
    def wait(seconds):
        calls.append(seconds)
        return connected
    return wait, calls


def test_windows_first_release_install_past_300s_succeeds(monkeypatch, capsys):
    monkeypatch.setattr(relay.sys, "platform", "win32")
    timeouts = []
    wait, _calls = _waits()
    outcome = relay.install(local_destination=False, environment="upyoke",
                            runner=_installer(OBSERVED_FIRST_INSTALL_SECONDS, timeouts),
                            wait_for_connection=wait)
    assert outcome == relay.RelayInstallOutcome(installed=True, reused=False, connected=True)
    assert timeouts == [relay_wait.RELAY_INSTALL_TIMEOUT_SECONDS]
    assert 300 < OBSERVED_FIRST_INSTALL_SECONDS < relay_wait.RELAY_INSTALL_TIMEOUT_SECONDS
    assert "Waiting by design: the machine relay installer" in capsys.readouterr().err
    assert "times out after 15m at most" in relay_wait.announce_install(write=lambda _l: None)


def test_windows_install_past_the_bound_names_timeout_and_recovery(monkeypatch):
    monkeypatch.setattr(relay.sys, "platform", "win32")
    beyond = relay_wait.RELAY_INSTALL_TIMEOUT_SECONDS + 1
    with pytest.raises(relay.OnboardSessionRelayError) as raised:
        relay.install(local_destination=False, environment="upyoke",
                      runner=_installer(beyond), wait_for_connection=lambda _s: True)
    message = str(raised.value)
    assert f"did not finish within {relay_wait.RELAY_INSTALL_TIMEOUT_SECONDS} seconds" in message
    assert "`yoke --env upyoke relay status`" in message
    assert "`yoke --env upyoke relay install`" in message


def test_windows_satisfied_relay_still_waits_for_its_heartbeat(monkeypatch):
    monkeypatch.setattr(relay.sys, "platform", "win32")
    commands = []
    def run(argv, **kwargs):
        commands.append(argv[3])
        return subprocess.CompletedProcess(argv, 0, "", "")
    wait, calls = _waits(connected=False)
    outcome = relay.install(local_destination=False, environment="upyoke",
                            runner=run, wait_for_connection=wait)
    assert commands == ["status"]
    assert calls == [relay_wait.RELAY_CONNECT_WAIT_SECONDS]
    assert outcome == relay.RelayInstallOutcome(installed=True, reused=True, connected=False)


def test_windows_fresh_install_waits_with_the_heartbeat_bound(monkeypatch):
    monkeypatch.setattr(relay.sys, "platform", "win32")
    wait, calls = _waits()
    relay.install(local_destination=False, environment="upyoke",
                  runner=_installer(1), wait_for_connection=wait)
    assert calls == [relay_wait.RELAY_CONNECT_WAIT_SECONDS] == [300]
    assert relay_wait.RELAY_CONNECT_WAIT_SECONDS > OBSERVED_FIRST_HEARTBEAT_SECONDS


def test_windows_heartbeat_timeout_reports_pending_not_fail(monkeypatch):
    rows = [{"hc": "HC-" + slug, "severity": "PASS"} for slug in doctor_install.install_slugs()]
    relay_row = next(row for row in rows if row["hc"] == "HC-session-relay")
    relay_row.update(severity="FAIL", detail="no currently connected relay heartbeat")

    def doctor_run(args):
        print(json.dumps({"success": True, "result": {"results": rows}}))
        return 1

    monkeypatch.setattr(doctor, "doctor_run", doctor_run)
    report = {"session_relay": {"installed": True, "connected": False, "environment": "upyoke"}}
    result = doctor_install.setup_readiness(report, {"project_slug": "sample"})
    assert result["ready"] and result["exit_code"] == 0
    assert relay_row not in result["results"]
    assert result["pending"] == [relay_wait.pending_heartbeat("upyoke")]
    rendered = render_human({"mode": "hosted", "config_path": "config", "applied": True,
                             "plan": {"steps": []}, "identity": {}, "next_steps": [],
                             "install_health": result})
    assert "FAIL: HC-session-relay" not in rendered
    assert "first heartbeat had not arrived within 300 seconds: session-relay" in rendered
    assert "Next: Run `yoke --env upyoke relay status`" in rendered

    heard = {"session_relay": {"installed": True, "connected": True, "environment": "upyoke"}}
    result = doctor_install.setup_readiness(heard, {"project_slug": "sample"})
    assert not result["ready"] and "pending" not in result
    assert relay_row in result["results"]
