"""Windows sign-in falls back to the printed link and code without a browser."""

from __future__ import annotations

import webbrowser

import pytest

from yoke_cli.config import hosted_machine_browser as browser

pytestmark = pytest.mark.windows

URL = "https://upyoke.com/device?code=ABCD-1234"


def _never(*_args, **_kwargs):
    raise AssertionError("no browser may be started")


@pytest.mark.parametrize("variable", ["SSH_CONNECTION", "SSH_CLIENT"])
def test_windows_ssh_session_opens_nothing(monkeypatch, variable: str) -> None:
    monkeypatch.setattr(webbrowser, "open", _never)

    result = browser.open_url(URL, platform="win32", environ={variable: "10.0.0.2 5 22"})

    assert result == browser.BrowserOpenResult(
        opened=False, reason="browser_display_unavailable"
    )


def test_windows_without_default_browser_reports_why(monkeypatch) -> None:
    # webbrowser's Windows opener returns False when os.startfile has no
    # handler for https: links (no default browser is set).
    monkeypatch.setattr(webbrowser, "open", lambda _url: False)

    result = browser.open_url(URL, platform="win32", environ={})

    assert result.opened is False
    assert result.attempted is True
    assert result.reason == "webbrowser.open returned False"


def test_windows_desktop_opens_the_default_browser(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    result = browser.open_url(URL, platform="win32", environ={})

    assert result == browser.BrowserOpenResult(opened=True, method="webbrowser")
    assert opened == [URL]


def test_connect_over_ssh_on_windows_prints_the_code_flow(monkeypatch, capsys) -> None:
    import sys

    from yoke_cli.commands import connect as command
    from yoke_cli.config import hosted_machine_authorization as auth

    pending = auth.PendingMachineAuthorization(
        "https://upyoke.com", "device-secret", "ABCD-1234",
        "https://upyoke.com/device", URL, 60, 2,
    )
    monkeypatch.setattr(auth, "start", lambda *a, **kw: pending)
    monkeypatch.setattr(
        auth,
        "complete",
        lambda *a, **kw: auth.HostedMachineCredential(
            "https://team.example", "team", "private-token"
        ),
    )
    monkeypatch.setattr(
        command.server_connect,
        "connect_server",
        lambda *a, **kw: {"api_url": "https://team.example", "env": "team", "activated": True},
    )
    monkeypatch.setattr(webbrowser, "open", _never)
    monkeypatch.setattr(
        command.setup_browser,
        "open_url",
        lambda url: browser.open_url(
            url, platform="win32", environ={"SSH_CONNECTION": "10.0.0.2 5 22"}
        ),
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(command, "_resolve_session_id", lambda: None)
    monkeypatch.setattr(command, "running_harness_family", lambda: None)

    assert command.connect([]) == 0

    out = capsys.readouterr().out
    assert f"Open {URL}" in out
    assert "ABCD-1234" in out
    assert "The browser did not open (browser_display_unavailable)" in out
