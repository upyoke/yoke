"""Windows setup installs a per-user task and renders restriction recovery."""

import subprocess

from yoke_cli.config import onboard_session_relay as relay
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
