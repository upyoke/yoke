"""Setup names the exact supervisor document the installer will write."""

import hashlib
import json

import pytest

from yoke_cli.config import onboard_session_relay as relay
from yoke_contracts.machine_config.relay_instance import resolve_relay_instance
from yoke_core.tools.session_relay_plist import relay_launchd_paths
from yoke_core.tools.session_relay_systemd import relay_unit_path


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("prod", [False, True])
def test_preview_progress_and_report_match_installer(
    monkeypatch, tmp_path, platform, prod
):
    monkeypatch.setattr(relay.sys, "platform", platform)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "selected",
                "projects": [],
                "connections": {
                    "selected": {
                        "transport": "https",
                        "prod": prod,
                        "api_url": "https://plane.example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": "~/.yoke/secrets/token",
                        },
                    }
                },
            }
        )
    )
    instance = resolve_relay_instance(config_path=config, environment="selected")
    expected = (
        relay_launchd_paths(instance=instance).plist
        if platform == "darwin"
        else relay_unit_path(instance)
    )
    plan = relay.plan_steps(
        local_destination=False, config_path=config, environment="selected"
    )
    assert plan[0]["target"].endswith(expected.name)
    assert "[" not in plan[0]["target"]
    monkeypatch.setattr(
        relay, "install", lambda **kwargs: relay.RelayInstallOutcome(True, False)
    )
    events, report = [], {}
    relay.apply(
        lambda *event: events.append(event),
        report,
        local_destination=False,
        config_path=config,
        environment="selected",
    )
    assert events[0] == (plan[0]["action"], plan[0]["target"], "running")
    fragment = report["session_relay"]
    key = "plist" if platform == "darwin" else "unit"
    assert fragment[key] == plan[0]["target"]
    assert any(expected.name in line for line in relay.report_complete_lines(fragment))


@pytest.mark.parametrize("local", [False, True])
def test_new_connection_preview_has_the_stable_instance_name(
    monkeypatch, tmp_path, local
):
    monkeypatch.setattr(relay.sys, "platform", "darwin")
    config = tmp_path / "config.json"
    digest = hashlib.sha256(f"{config.resolve()}\0selected".encode()).hexdigest()[:16]
    plan = relay.plan_steps(
        local_destination=local, config_path=config, environment="selected"
    )
    assert (
        plan[0]["target"] == f"~/Library/LaunchAgents/com.upyoke.relay.{digest}.plist"
    )
