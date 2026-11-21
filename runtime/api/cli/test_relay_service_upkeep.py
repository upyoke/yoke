"""`yoke update` and `yoke project refresh` reinstall an outdated relay service."""

import json
import subprocess

import pytest

from yoke_cli.commands.adapters import install as install_adapter
from yoke_cli.commands.adapters import self_update as self_update_adapter
from yoke_cli.config import relay_service_upkeep as upkeep
from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV


class Yoke:
    def __init__(self, status, install_code=0):
        self.status = status
        self.install_code = install_code
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[4] == "status":
            out = self.status if isinstance(self.status, str) else json.dumps(self.status)
            return subprocess.CompletedProcess(argv, 1, out, "")
        return subprocess.CompletedProcess(argv, self.install_code, "", "relay_task_scheduler_unavailable: denied")

    def actions(self):
        return [argv[4] for argv, _ in self.calls]


def _status(**overrides):
    return {"supported": True, "service_present": True, "service_current": True, **overrides}


def _converge(yoke, tmp_path=None):
    config = tmp_path / "config.json" if tmp_path else None
    return upkeep.converge_relay("prod", yoke_bin="yoke", config_path=config, run=yoke)


def test_outdated_service_is_reinstalled_through_the_updated_cli(tmp_path):
    yoke = Yoke(_status(service_current=False))
    assert _converge(yoke, tmp_path) == {"environment": "prod", "status": "refreshed"}
    assert yoke.actions() == ["status", "install"]
    argv, kwargs = yoke.calls[1]
    assert argv == ["yoke", "--env", "prod", "relay", "install", "--json"]
    assert kwargs["env"][CONFIG_FILE_ENV] == str(tmp_path / "config.json")


@pytest.mark.parametrize("status, expected", [
    (_status(), "current"),
    (_status(service_present=False, service_current=False), "not_installed"),
    (_status(supported=False, supervision_reason="Task Scheduler disabled"), "skipped"),
    ("", "skipped"),
])
def test_current_missing_or_unsupported_services_are_left_alone(status, expected):
    yoke = Yoke(status)
    assert _converge(yoke)["status"] == expected
    assert yoke.actions() == ["status"]


def test_failed_reinstall_names_its_refusal_and_recovery():
    yoke = Yoke(_status(service_current=False), install_code=1)
    outcome = _converge(yoke)
    assert outcome["status"] == "failed"
    assert "relay_task_scheduler_unavailable: denied" in outcome["detail"]
    (line,) = upkeep.summary_lines([outcome])
    assert line.startswith("error: relay_service_refresh_failed: the prod relay service")
    assert "`yoke --env prod relay install`" in line


def test_every_configured_environment_is_converged(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"connections": {"stage": {}, "prod": {}}}), encoding="utf-8")
    monkeypatch.setattr(upkeep.machine_config, "load_config", lambda path: json.loads(config.read_text()))
    assert upkeep._environments(config) == ["prod", "stage"]


def test_project_refresh_fails_loudly_when_a_relay_reinstall_fails(monkeypatch, capsys):
    failure = {"environment": "prod", "status": "failed", "detail": "denied", "recovery": "run it"}
    monkeypatch.setattr(upkeep, "converge_relays", lambda **kw: [failure])
    assert install_adapter._converge_relay_services(None) == 1
    assert "relay_service_refresh_failed" in capsys.readouterr().err
    monkeypatch.setattr(upkeep, "converge_relays", lambda **kw: [{"environment": "prod", "status": "refreshed"}])
    assert install_adapter._converge_relay_services(None) == 0
    assert "Reinstalled the prod relay service" in capsys.readouterr().err


def test_yoke_update_reports_relay_refresh_and_fails_on_its_failure(monkeypatch, capsys):
    result = {
        "old_version": "1", "new_version": "2", "already_current": False, "direction": "upgrade",
        "pinned": False, "channel": "stable", "channel_version": "2", "base_url": "",
        "credential_helper_configured": None, "credential_helper_repaired": False,
        "credential_helper_rewritten": [], "credential_helper_error": None,
        "relay_services": [{"environment": "prod", "status": "failed", "detail": "denied", "recovery": "run it"}],
    }
    monkeypatch.setattr(self_update_adapter.self_update, "run_update", lambda **kw: result)
    assert self_update_adapter.update(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    result["relay_services"] = [{"environment": "prod", "status": "refreshed"}]
    assert self_update_adapter.update([]) == 0
    assert "Reinstalled the prod relay service for this release." in capsys.readouterr().out


def test_self_update_converges_relays_with_the_updated_binary(monkeypatch):
    from yoke_cli.config import self_update

    monkeypatch.setattr(self_update.project_update, "refresh_current", lambda yoke_bin: {"status": "not_installed"})
    calls = []
    monkeypatch.setattr(upkeep, "converge_relays", lambda **kw: calls.append(kw) or [])
    result = self_update._with_project_refresh("/new/yoke", {})
    assert calls == [{"yoke_bin": "/new/yoke"}] and result["relay_services"] == []
