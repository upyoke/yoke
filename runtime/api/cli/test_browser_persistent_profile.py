"""Persistent browser profile contract: one profile per project, operator-signed."""

from __future__ import annotations

import stat
import subprocess

import pytest

from yoke_cli.config import browser_profile
from yoke_cli.commands import browser_authorize as authorize_command
from yoke_harness import browser_client, browser_qa_daemon


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_profile_path_is_per_project_under_capability_secrets(machine_home) -> None:
    directory = browser_profile.profile_dir("acme")

    assert directory == (
        machine_home / "secrets" / "capability-secrets" / "acme"
        / "browser-control" / "profile"
    )
    assert browser_profile.profile_dir("other") != directory


def test_ensure_profile_dir_is_owner_only(machine_home) -> None:
    directory = browser_profile.ensure_profile_dir("acme")

    assert directory.is_dir()
    for candidate in (directory, directory.parent, directory.parent.parent):
        mode = stat.S_IMODE(candidate.stat().st_mode)
        assert mode == 0o700, f"{candidate} is {oct(mode)}"


def test_unauthorized_project_resolves_to_no_profile(machine_home) -> None:
    resolved, note = browser_profile.resolve_authorized_profile("acme")

    assert resolved is None
    assert "yoke browser authorize --project acme" in note


def test_note_names_other_authorized_projects(machine_home) -> None:
    browser_profile.ensure_profile_dir("acme")

    resolved, note = browser_profile.resolve_authorized_profile("beta")

    assert resolved is None
    assert "acme" in note
    assert browser_profile.authorized_project_keys() == ["acme"]


def test_authorized_project_resolves_to_its_profile(machine_home) -> None:
    created = browser_profile.ensure_profile_dir("acme")

    resolved, note = browser_profile.resolve_authorized_profile("acme")

    assert resolved == created
    assert str(created) in note


def _stub_daemon_start(monkeypatch, tmp_path, state_loads):
    browser = tmp_path / "browser"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    browser.joinpath("node_modules", "playwright").mkdir(parents=True)
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client, "_state_file_path", lambda: tmp_path / "state.json",
    )
    monkeypatch.setattr(browser_client.time, "sleep", lambda _seconds: None)

    loads = {"count": 0}

    def fake_load(path=None):
        index = min(loads["count"], len(state_loads) - 1)
        loads["count"] += 1
        return state_loads[index]

    monkeypatch.setattr(browser_client.DaemonState, "load", staticmethod(fake_load))
    monkeypatch.setattr(
        browser_client,
        "daemon_request",
        lambda *_args, **_kwargs: {"success": True, "data": {"health": "healthy"}},
    )
    monkeypatch.setattr(
        browser_client.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "ok" if command[:2] == ["node", "-e"] else "", "",
        ),
    )

    launched: list[list[str]] = []

    class FakeProcess:
        pid = 4242

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

        def kill(self):
            pass

    def fake_popen(command, **_kwargs):
        launched.append(list(command))
        return FakeProcess()

    monkeypatch.setattr(browser_client.subprocess, "Popen", fake_popen)
    return launched


def _healthy_state(profile_dir: str) -> browser_client.DaemonState:
    return browser_client.DaemonState(
        pid=4242,
        endpoint="http://127.0.0.1:9000",
        health="healthy",
        profile_dir=profile_dir,
    )


def test_daemon_start_passes_the_profile_directory(tmp_path, monkeypatch) -> None:
    launched = _stub_daemon_start(
        monkeypatch, tmp_path, [None, _healthy_state("/profiles/acme")],
    )

    result = browser_client.daemon_start(profile_dir="/profiles/acme")

    assert result["status"] == "started"
    assert ["--profile-dir", "/profiles/acme"] == launched[0][-4:-2]


def test_daemon_start_without_a_profile_launches_clean(tmp_path, monkeypatch) -> None:
    launched = _stub_daemon_start(monkeypatch, tmp_path, [None, _healthy_state("")])

    result = browser_client.daemon_start()

    assert result["status"] == "started"
    assert "--profile-dir" not in launched[0]


def test_daemon_start_reuses_a_daemon_on_the_same_profile(tmp_path, monkeypatch) -> None:
    _stub_daemon_start(monkeypatch, tmp_path, [_healthy_state("/profiles/acme")])
    monkeypatch.setattr(browser_client, "daemon_running", lambda state=None: True)

    result = browser_client.daemon_start(profile_dir="/profiles/acme")

    assert result["status"] == "already_running"


def test_daemon_start_restarts_on_a_different_profile(tmp_path, monkeypatch) -> None:
    launched = _stub_daemon_start(
        monkeypatch,
        tmp_path,
        [_healthy_state("/profiles/beta"), _healthy_state("/profiles/acme")],
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state=None: True)
    stopped: list[bool] = []
    monkeypatch.setattr(
        browser_client, "daemon_stop", lambda: stopped.append(True) or "stopped",
    )

    result = browser_client.daemon_start(profile_dir="/profiles/acme")

    assert stopped == [True]
    assert result["status"] == "started"
    assert ["--profile-dir", "/profiles/acme"] == launched[0][-4:-2]


def test_ensure_daemon_running_uses_the_projects_profile(
    machine_home, monkeypatch,
) -> None:
    profile = browser_profile.ensure_profile_dir("acme")
    calls: list[str | None] = []

    monkeypatch.setattr(
        browser_client.DaemonState, "load", staticmethod(lambda path=None: None),
    )
    monkeypatch.setattr(
        browser_client,
        "daemon_start",
        lambda profile_dir=None: calls.append(profile_dir) or {"status": "started"},
    )

    assert browser_qa_daemon.ensure_daemon_running(project="acme") is None
    assert calls == [str(profile)]


def test_authorize_creates_the_profile_and_opens_the_window(
    machine_home, tmp_path, monkeypatch,
) -> None:
    runtime_dir = tmp_path / "browser-runtime"
    runtime_dir.joinpath("src").mkdir(parents=True)
    runtime_dir.joinpath("src", "authorize.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized", lambda: runtime_dir,
    )
    monkeypatch.setattr(
        browser_client.DaemonState, "load", staticmethod(lambda path=None: None),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        authorize_command.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(list(command))
        or subprocess.CompletedProcess(command, 0),
    )

    assert authorize_command.browser_authorize(["--project", "acme"]) == 0

    profile = browser_profile.profile_dir("acme")
    assert profile.is_dir()
    assert commands[0][:2] == ["node", str(runtime_dir / "src" / "authorize.js")]
    assert commands[0][2:4] == ["--profile-dir", str(profile)]


def test_authorize_reports_a_missing_runtime(machine_home, tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "browser-runtime"
    runtime_dir.mkdir()
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized", lambda: runtime_dir,
    )

    assert authorize_command.browser_authorize(["--project", "acme"]) == 2
