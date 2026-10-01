"""WSL browser fallbacks retain argv boundaries and failed-attempt evidence."""

import subprocess

import pytest

from yoke_cli.config import hosted_machine_browser as browser


@pytest.mark.parametrize("first_status", [0, 1, None])
def test_wslview_then_explorer_reach_the_windows_browser(monkeypatch, first_status):
    calls = []
    monkeypatch.setattr(
        browser.shutil,
        "which",
        lambda name: (
            None if name == "wslview" and first_status is None else "/bin/" + name
        ),
    )

    def run(argv, **kwargs):
        calls.append(argv)
        status = first_status if argv[0].endswith("wslview") else 0
        return subprocess.CompletedProcess(argv, status, "", "failed" if status else "")

    monkeypatch.setattr(browser.subprocess, "run", run)
    url = "http://localhost:8060/?token=a&other=b"
    result = browser.open_url(
        url,
        platform="linux",
        environ={"WSL_DISTRO_NAME": "Ubuntu"},
        browser_open=lambda _: False,
    )
    assert result.opened
    assert result.method == ("wslview" if first_status == 0 else "explorer.exe")
    assert all(argv[1:] == [url] for argv in calls)
    assert "webbrowser.open returned False" in result.reason


def test_wsl_missing_openers_report_recovery_evidence(monkeypatch):
    monkeypatch.setattr(browser.shutil, "which", lambda _: None)
    result = browser.open_url(
        "https://example.invalid",
        platform="linux",
        environ={"WSL_INTEROP": "/run/interop"},
        browser_open=lambda _: False,
    )
    assert not result.opened
    assert "wslview unavailable" in result.reason
    assert "explorer.exe unavailable" in result.reason
