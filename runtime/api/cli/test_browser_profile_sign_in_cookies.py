"""A sign-in survives the window closing: kept cookies, and a clean reset."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from runtime.api.cli.browser_toolchain_test_support import (
    install_fake_toolchain,
)
from yoke_cli.config import browser_profile
from yoke_cli.config.browser_profile_cookies import (
    SIGN_IN_COOKIE_LIFETIME_DAYS,
    SignInCookieError,
    cookie_store_path,
    keep_sign_in_cookies,
)
from yoke_cli.commands import browser_authorize as authorize_command
from yoke_harness import browser_client

CHROMIUM_EPOCH_OFFSET_SECONDS = 11_644_473_600

COOKIE_TABLE = (
    "CREATE TABLE cookies(creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, "
    "name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL, "
    "expires_utc INTEGER NOT NULL, has_expires INTEGER NOT NULL, "
    "is_persistent INTEGER NOT NULL)"
)


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _cookie_store(profile: Path, rows) -> Path:
    store = cookie_store_path(profile)
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(store))
    with connection:
        connection.execute(COOKIE_TABLE)
        connection.executemany(
            "INSERT INTO cookies VALUES (0, ?, ?, '', X'00', ?, ?, ?)", rows,
        )
    connection.close()
    return store


def _rows(store: Path):
    connection = sqlite3.connect(str(store))
    try:
        return connection.execute(
            "SELECT name, has_expires, is_persistent, expires_utc FROM cookies "
            "ORDER BY name",
        ).fetchall()
    finally:
        connection.close()


def test_a_session_cookie_is_given_an_expiry(tmp_path) -> None:
    profile = tmp_path / "profile"
    store = _cookie_store(profile, [("app.example", "sid", 0, 0, 0)])
    now = time.time()

    assert keep_sign_in_cookies(profile, now=now) == 1

    name, has_expires, is_persistent, expires_utc = _rows(store)[0]
    assert (name, has_expires, is_persistent) == ("sid", 1, 1)
    expected = (
        now + SIGN_IN_COOKIE_LIFETIME_DAYS * 86_400 + CHROMIUM_EPOCH_OFFSET_SECONDS
    ) * 1_000_000
    assert abs(expires_utc - expected) < 1_000_000


def test_a_cookie_that_already_expires_is_left_alone(tmp_path) -> None:
    profile = tmp_path / "profile"
    store = _cookie_store(profile, [("app.example", "remember", 99, 1, 1)])

    assert keep_sign_in_cookies(profile) == 0
    assert _rows(store) == [("remember", 1, 1, 99)]


def test_a_profile_that_was_never_signed_into_keeps_nothing(tmp_path) -> None:
    assert keep_sign_in_cookies(tmp_path / "profile") == 0


def test_an_unusable_cookie_store_names_its_recovery(tmp_path) -> None:
    profile = tmp_path / "profile"
    store = cookie_store_path(profile)
    store.parent.mkdir(parents=True)
    store.write_text("not a database", encoding="utf-8")

    with pytest.raises(SignInCookieError) as raised:
        keep_sign_in_cookies(profile)

    assert "yoke browser authorize --reset" in str(raised.value)


def _stub_authorize_runtime(tmp_path, monkeypatch) -> list[dict]:
    runtime_dir = tmp_path / "browser-runtime"
    runtime_dir.joinpath("src").mkdir(parents=True)
    runtime_dir.joinpath("src", "authorize.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized", lambda: runtime_dir,
    )
    monkeypatch.setattr(
        browser_client.DaemonState, "load", staticmethod(lambda path=None: None),
    )
    calls: list[dict] = []

    def fake_run(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(authorize_command.subprocess, "run", fake_run)
    install_fake_toolchain(monkeypatch, tmp_path / "node-bin")
    return calls


def test_authorize_keeps_the_sign_in_when_the_window_closes(
    machine_home, tmp_path, monkeypatch, capsys,
) -> None:
    _stub_authorize_runtime(tmp_path, monkeypatch)
    store = _cookie_store(
        browser_profile.ensure_profile_dir("acme"), [("app.example", "sid", 0, 0, 0)],
    )

    assert authorize_command.browser_authorize(
        ["--project", "acme", "--json"],
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["kept_sign_in_cookies"] == 1
    assert payload["reset"] is False
    assert _rows(store)[0][:3] == ("sid", 1, 1)


def test_authorize_reports_an_unusable_cookie_store(
    machine_home, tmp_path, monkeypatch, capsys,
) -> None:
    _stub_authorize_runtime(tmp_path, monkeypatch)
    store = cookie_store_path(browser_profile.ensure_profile_dir("acme"))
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("not a database", encoding="utf-8")

    assert authorize_command.browser_authorize(["--project", "acme"]) == 1
    assert "cookie store" in capsys.readouterr().err


def test_reset_removes_the_profile_before_opening_the_window(
    machine_home, tmp_path, monkeypatch, capsys,
) -> None:
    calls = _stub_authorize_runtime(tmp_path, monkeypatch)
    profile = browser_profile.ensure_profile_dir("acme")
    _cookie_store(profile, [("app.example", "sid", 0, 0, 0)])

    assert authorize_command.browser_authorize(["--project", "acme", "--reset"]) == 0

    assert not cookie_store_path(profile).exists()
    assert profile.is_dir(), "the fresh window still gets a profile directory"
    assert calls[0]["command"][2:4] == ["--profile-dir", str(profile)]
    assert "Removed the previous acme browser profile" in capsys.readouterr().out


def test_reset_without_a_profile_still_opens_the_window(
    machine_home, tmp_path, monkeypatch, capsys,
) -> None:
    calls = _stub_authorize_runtime(tmp_path, monkeypatch)

    assert authorize_command.browser_authorize(["--project", "acme", "--reset"]) == 0

    assert len(calls) == 1
    assert "No acme browser profile to remove" in capsys.readouterr().out


def test_remove_profile_dir_reports_an_absent_profile(machine_home) -> None:
    assert browser_profile.remove_profile_dir("acme") is None


def test_the_daemon_keeps_the_sign_in_before_it_launches(
    tmp_path, monkeypatch,
) -> None:
    """The daemon's own refreshed session cookies survive its next start."""
    profile = tmp_path / "profile"
    store = _cookie_store(profile, [("app.example", "sid", 0, 0, 0)])
    order: list[str] = []

    def fake_keep(target):
        order.append("kept")
        assert Path(target) == profile
        return keep_sign_in_cookies(target)

    monkeypatch.setattr(browser_client, "keep_sign_in_cookies", fake_keep)
    _stub_daemon_launch(monkeypatch, tmp_path, order)

    assert browser_client.daemon_start(profile_dir=str(profile))["status"] == "started"
    assert order == ["kept", "launched"], "cookies are kept before Chromium opens them"
    assert _rows(store)[0][:3] == ("sid", 1, 1)


def test_a_daemon_start_survives_an_unusable_cookie_store(
    tmp_path, monkeypatch, capsys,
) -> None:
    """A profile that cannot be updated is named, not fatal: the run is signed out."""
    profile = tmp_path / "profile"
    store = cookie_store_path(profile)
    store.parent.mkdir(parents=True)
    store.write_text("not a database", encoding="utf-8")
    order: list[str] = []
    _stub_daemon_launch(monkeypatch, tmp_path, order)

    assert browser_client.daemon_start(profile_dir=str(profile))["status"] == "started"
    assert order == ["launched"]
    assert "Could not keep this profile's sign-in" in capsys.readouterr().err


def _stub_daemon_launch(monkeypatch, tmp_path, order: list[str]) -> None:
    browser = tmp_path / "browser"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    browser.joinpath("node_modules", "playwright").mkdir(parents=True)
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client, "_state_file_path", lambda: tmp_path / "state.json",
    )
    monkeypatch.setattr(browser_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        staticmethod(lambda path=None: browser_client.DaemonState(
            pid=4242, endpoint="http://127.0.0.1:9000", health="healthy",
        )),
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state=None: False)
    monkeypatch.setattr(
        browser_client,
        "_probe_daemon_health",
        lambda state, timeout=1: {"health": "healthy"},
    )
    monkeypatch.setattr(
        browser_client.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "ok" if command[1:2] == ["-e"] else "", "",
        ),
    )

    class FakeProcess:
        pid = 4242

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

    def fake_popen(command, **_kwargs):
        order.append("launched")
        return FakeProcess()

    monkeypatch.setattr(browser_client.subprocess, "Popen", fake_popen)
    install_fake_toolchain(monkeypatch, tmp_path / "node-bin")
