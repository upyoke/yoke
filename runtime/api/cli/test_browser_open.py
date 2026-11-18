"""`yoke browser open` shows a page in an authorized identity's live profile."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.commands import browser_open, browser_sign_in
from yoke_cli.config import browser_profile, hosted_machine_browser


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_an_unauthorized_identity_refuses_with_the_authorize_command(
    machine_home, capsys
):
    assert browser_open.browser_open(
        ["--project", "acme", "--identity", "operator", "--json", "https://x.test/"]
    ) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error.startswith("browser_identity_not_authorized:")
    assert (
        "yoke browser authorize --project acme --identity operator --test-machine"
        in error
    )


def _runtime(monkeypatch, tmp_path, stdout):
    runtime = browser_sign_in.BrowserRuntime(tmp_path, tmp_path / "node", {"K": "V"})
    monkeypatch.setattr(browser_sign_in, "prepare_browser_runtime", lambda s: runtime)
    stopped, ran = [], []
    from yoke_harness import browser_identity_check

    monkeypatch.setattr(
        browser_identity_check,
        "stop_profile_daemon",
        lambda client, profile: stopped.append(profile),
    )

    def run(argv, **kwargs):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(browser_open.subprocess, "run", run)
    return stopped, ran


def test_the_window_opens_on_the_live_profile_after_its_daemon_stops(
    machine_home, monkeypatch, tmp_path, capsys
):
    profile = browser_profile.ensure_profile_dir("acme", identity="operator")
    stopped, ran = _runtime(
        monkeypatch,
        tmp_path,
        json.dumps({"ok": True, "opened": "new_window", "devtools_port": 4321}),
    )
    assert browser_open.browser_open(
        ["--project", "acme", "--identity", "operator", "--json", "https://x.test/a"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "opened": "new_window",
        "devtools_port": 4321,
        "profile_dir": str(profile),
    }
    assert stopped == [profile]
    assert ran == [
        [
            str(tmp_path / "node"),
            str(tmp_path / "src" / "open.js"),
            "--profile-dir",
            str(profile),
            "--url",
            "https://x.test/a",
        ]
    ]


def test_a_launcher_refusal_is_passed_through_by_name(
    machine_home, monkeypatch, tmp_path, capsys
):
    browser_profile.ensure_profile_dir("acme", identity="operator")
    _runtime(
        monkeypatch,
        tmp_path,
        json.dumps({"ok": False, "error": "browser_open_not_ready: no port"}),
    )
    assert browser_open.browser_open(
        ["--project", "acme", "--identity", "operator", "https://x.test/"]
    ) == 1
    assert "browser_open_not_ready: no port" in capsys.readouterr().err


def _completed(argv, code=0, stderr=""):
    return subprocess.CompletedProcess(argv, code, "", stderr)


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_browser_variable_wins_on_every_platform(monkeypatch, platform):
    ran = []
    monkeypatch.setattr(
        hosted_machine_browser.terminal_detached_process,
        "run",
        lambda argv, **kw: ran.append(argv) or _completed(argv),
    )
    result = hosted_machine_browser.open_url(
        "https://app.test/connect?user_code=K7F2",
        platform=platform,
        environ={
            "BROWSER": "env -u YOKE_MACHINE_HOME '/opt/my yoke' browser open "
            "--project acme --identity operator %s",
            "SSH_CONNECTION": "1",
        },
    )
    assert result.opened and result.method == "BROWSER"
    assert ran == [
        [
            "env", "-u", "YOKE_MACHINE_HOME", "/opt/my yoke", "browser", "open",
            "--project", "acme", "--identity", "operator",
            "https://app.test/connect?user_code=K7F2",
        ]
    ]


def test_browser_variable_tries_each_command_and_records_failures(monkeypatch):
    import os

    ran = []

    def run(argv, **kw):
        ran.append(argv)
        return _completed(argv, 1, "no display") if argv[0] == "first" else _completed(argv)

    monkeypatch.setattr(hosted_machine_browser.terminal_detached_process, "run", run)
    result = hosted_machine_browser.open_url(
        "https://u.test/", platform="linux", environ={"BROWSER": f"first{os.pathsep}second"}
    )
    assert ran == [["first", "https://u.test/"], ["second", "https://u.test/"]]
    assert result.opened and "BROWSER first exited 1: no display" in result.reason


def test_browser_variable_failure_is_the_answer(monkeypatch):
    monkeypatch.setattr(
        hosted_machine_browser.terminal_detached_process,
        "run",
        lambda argv, **kw: _completed(argv, 1, "browser_identity_not_authorized: x"),
    )
    result = hosted_machine_browser.open_url(
        "https://u.test/", platform="darwin", environ={"BROWSER": "launcher %s"}
    )
    assert not result.opened
    assert "browser_identity_not_authorized" in result.reason
