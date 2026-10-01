"""Linux onboarding installs the same relay through its native supervisor."""

import subprocess

from yoke_cli.config import onboard_session_relay as relay
from yoke_cli.commands.adapters.session_control_relay_output import relay_status_fields


def test_linux_plans_and_installs_both_build_sources(monkeypatch):
    monkeypatch.setattr(relay.sys, "platform", "linux")
    for local in (False, True):
        steps = relay.plan_steps(local_destination=local)
        assert steps[0]["action"] == "install-session-relay-unit"
        assert steps[1]["action"] == "enable-session-relay-user-service"
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(
                argv, 1 if argv[3] == "status" else 0, "", ""
            )

        outcome = relay.install(
            local_destination=local, environment="selected", runner=run
        )
        assert outcome.installed and not outcome.reused
        assert len(calls) == 2
        assert calls[1][3:] == ["install", "--environment", "selected"]
        fragment = relay.report_fragment(
            planned=True, installed=True, local_destination=local
        )
        assert "unit" in fragment and "plist" not in fragment
        lines = relay.report_complete_lines(fragment)
        assert any("logs out" in line for line in lines)
        assert any("linger is disabled" in line for line in lines)


def test_linux_status_text_names_service_state_and_logout():
    fields = dict(
        relay_status_fields(
            {
                "unit_name": "com.upyoke.relay.service",
                "unit_present": True,
                "unit_current": True,
                "unit_path": "/home/user/.config/systemd/user/relay.service",
                "enabled": True,
                "loaded": True,
                "logout_behavior": "Stops at logout",
            }
        )
    )
    assert fields["Configuration present"] and fields["Configuration current"]
    assert fields["Enabled at login"]
    assert fields["Logout behavior"] == "Stops at logout"
