"""Opening the approval URL records why it failed and falls back on macOS."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import hosted_machine_browser as browser

PENDING = auth.PendingMachineAuthorization(
    platform_url="https://app.upyoke.com",
    device_code="device-secret",
    user_code="ABCD-2345",
    verification_uri="https://app.upyoke.com/connect",
    verification_uri_complete="https://app.upyoke.com/connect?user_code=ABCD-2345",
    expires_in=600,
    interval=2,
)


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["open"], returncode, stdout="", stderr=stderr)


def test_webbrowser_success_needs_no_fallback() -> None:
    opened: list[str] = []
    macos_calls: list[str] = []

    result = browser.open_browser(
        PENDING,
        browser_open=lambda url: opened.append(url) or True,
        macos_open=lambda url: macos_calls.append(url) or _completed(0),
        platform=browser.MACOS_PLATFORM,
    )

    assert result == browser.BrowserOpenResult(opened=True, method="webbrowser")
    assert opened == [PENDING.verification_uri_complete]
    assert macos_calls == []


def test_macos_open_command_covers_a_false_webbrowser_return() -> None:
    macos_calls: list[str] = []

    result = browser.open_browser(
        PENDING,
        browser_open=lambda _url: False,
        macos_open=lambda url: macos_calls.append(url) or _completed(0),
        platform=browser.MACOS_PLATFORM,
    )

    assert result.opened is True
    assert result.method == "open"
    assert result.reason == "webbrowser.open returned False"
    assert macos_calls == [PENDING.verification_uri_complete]


def test_every_failed_attempt_is_named_in_order() -> None:
    def _raise(_url: str) -> bool:
        raise RuntimeError("no display")

    result = browser.open_browser(
        PENDING,
        browser_open=_raise,
        macos_open=lambda _url: _completed(1, stderr="LSOpenURLsWithRole() failed"),
        platform=browser.MACOS_PLATFORM,
    )

    assert result.opened is False
    assert result.method is None
    assert result.reason == (
        "webbrowser.open raised RuntimeError: no display; "
        "open command exited 1: LSOpenURLsWithRole() failed"
    )


def test_a_missing_open_command_is_a_named_failure_not_a_crash() -> None:
    def _missing(_url: str) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("open")

    result = browser.open_browser(
        PENDING,
        browser_open=lambda _url: False,
        macos_open=_missing,
        platform=browser.MACOS_PLATFORM,
    )

    assert result.opened is False
    assert "open command failed: FileNotFoundError: open" in (result.reason or "")


def test_other_platforms_report_the_webbrowser_failure_alone() -> None:
    macos_calls: list[str] = []

    result = browser.open_browser(
        PENDING,
        browser_open=lambda _url: False,
        macos_open=lambda url: macos_calls.append(url) or _completed(0),
        platform="linux",
    )

    assert result == browser.BrowserOpenResult(
        opened=False, reason="webbrowser.open returned False",
    )
    assert macos_calls == []


def test_complete_stops_at_once_when_the_wait_is_cancelled() -> None:
    polls: list[str] = []
    ticks = iter([0.0, 0.0, 0.0, 0.0])

    with pytest.raises(auth.HostedMachineAuthorizationCancelled):
        auth.complete(
            PENDING,
            opener=lambda *a, **k: polls.append("poll"),
            sleep=lambda _s: None,
            monotonic=lambda: next(ticks),
            cancelled=lambda: True,
        )

    assert polls == []
