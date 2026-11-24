"""The admission opener names the opener's reason code and never its detail."""

from __future__ import annotations

import pytest

from yoke_cli.config import browser_admission as admission
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult

URL = "http://127.0.0.1:8688/?token=private-admission-secret"


@pytest.fixture(autouse=True)
def _human_terminal(monkeypatch):
    monkeypatch.setattr(admission, "_resolve_session_id", lambda: None)
    monkeypatch.setattr(admission, "nearest_harness_family", lambda: None)


def _reason(opener_reason):
    result = admission.open_private_url(
        URL, opener=lambda _url: BrowserOpenResult(opened=False, reason=opener_reason)
    )
    assert not result.opened
    return result.reason


def test_a_named_opener_reason_reaches_the_caller():
    assert _reason("browser_display_unavailable") == "browser_display_unavailable"


def test_a_reason_carrying_the_url_keeps_only_its_code():
    reason = _reason(f"system_browser_open_failed: could not open {URL}")
    assert reason == "system_browser_open_failed"


def test_joined_attempts_report_the_first_code():
    reason = _reason(f"system_browser_unavailable; browser_runtime_open_failed: {URL}")
    assert reason == "system_browser_unavailable"


@pytest.mark.parametrize(
    "opener_reason",
    [None, "", "webbrowser.open returned False", f"BROWSER {URL} exited 1: no"],
)
def test_a_reason_without_a_code_stays_generic(opener_reason):
    assert _reason(opener_reason) == "browser_open_failed"


def test_an_opener_exception_stays_generic():
    def explode(url):
        raise OSError(f"could not open {url}")

    result = admission.open_private_url(URL, opener=explode)
    assert result.reason == "browser_open_failed"


@pytest.mark.parametrize("prefix", ["", "yoke browser open: "])
def test_browser_child_named_failure_survives_without_its_detail(monkeypatch, prefix):
    from types import SimpleNamespace

    from yoke_cli.config import hosted_machine_browser

    monkeypatch.setattr(
        hosted_machine_browser.terminal_detached_process,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"{prefix}browser_identity_not_authorized: cannot open {URL}",
        ),
    )
    result = admission.open_private_url(
        URL,
        opener=lambda url: hosted_machine_browser.open_url(
            url, environ={"BROWSER": "browser-command"}
        ),
    )
    assert result.reason == "browser_identity_not_authorized"
    assert URL not in repr(result)
