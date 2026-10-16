"""Native Safari approval is exact-target, visible-control automation.

The matcher and outcome contract shared with desktop Chromium is tested per
driver in runtime/harness/test_machine_approval_coordinates.py.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_harness.ssh_mac_browser_approval import approve_machine_in_safari

ENTRY_URL = "https://app.stage.upyoke.com/connect?user_code=AB12-CD34"
REDIRECT_URL = "https://app.stage.upyoke.com/orgs/acme/machine-approval/AB12-CD34"


def _completed(
    command: str,
    *,
    stdout: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, "")


@pytest.mark.parametrize(
    "starting_url",
    [
        ENTRY_URL,
        REDIRECT_URL,
        REDIRECT_URL + "?selection=all",
        REDIRECT_URL + "?selection=1,4",
    ],
)
def test_approval_targets_the_exact_code_tab_and_visible_button(starting_url) -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _completed(
            command,
            stdout=(
                starting_url + "\n"
                if "return tabURLs" in command
                else f"approved|{starting_url}|https://app.stage.upyoke.com/orgs/acme/frontier\n"
            ),
        )

    result = approve_machine_in_safari(
        run,
        verification_url="https://app.stage.upyoke.com/connect",
        user_code="AB12-CD34",
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.evidence == {
        "approval_entry": starting_url.removeprefix(
            "https://app.stage.upyoke.com"
        ).split("?")[0],
        "browser": "Safari",
        "result_url": "https://app.stage.upyoke.com/orgs/acme/frontier",
        "visible_control": "Approve machine",
    }
    assert len(commands) == 2
    assert ENTRY_URL in commands[1]
    assert starting_url in commands[1]
    assert "Approve machine" in commands[1]
    assert 'perform action "AXPress"' in commands[1]
    assert "resultURL is not matchedStartingURL" in commands[1]
    assert commands[1].index("is not matchedStartingURL") < commands[1].index("AXPress")
    assert 'return "approved|" & matchedStartingURL & "|" & resultURL' in commands[1]


@pytest.mark.parametrize(
    "starting_url",
    [
        REDIRECT_URL + "?selection=",
        REDIRECT_URL + "?selection=0",
        REDIRECT_URL + "?selection=01",
        REDIRECT_URL + "?selection=1,1",
        REDIRECT_URL + "?selection=1%2C4",
        REDIRECT_URL + "?selection=%61ll",
        REDIRECT_URL + "?selection=all&selection=all",
        REDIRECT_URL + "?selection=all&other=1",
        REDIRECT_URL + "?other=1",
        REDIRECT_URL + "?selection=all#fragment",
        REDIRECT_URL + "/extra?selection=all",
        REDIRECT_URL.replace("AB12-CD34", "EF56-GH78") + "?selection=all",
        REDIRECT_URL.replace("app.stage.upyoke.com", "evil.example") + "?selection=all",
    ],
)
def test_approval_refuses_noncanonical_or_unrelated_tabs(starting_url) -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _completed(
            command,
            stdout=(
                starting_url + "\n"
                if "return tabURLs" in command
                else "browser_tab_missing\n"
            ),
        )

    result = approve_machine_in_safari(
        run,
        verification_url="https://app.stage.upyoke.com/connect",
        user_code="AB12-CD34",
    )
    assert result.error_code == "machine_browser_tab_missing"
    assert starting_url not in commands[1]


@pytest.mark.parametrize("result_url", [ENTRY_URL, REDIRECT_URL])
def test_visible_connected_confirmation_accepts_only_the_same_allowed_tab(result_url):
    from yoke_harness.machine_browser_approval import approval_outcome

    result = approval_outcome(
        browser="Safari",
        state="approved_in_place",
        starting_url=ENTRY_URL,
        result_url=result_url,
        allowed_urls=[ENTRY_URL, REDIRECT_URL],
        expected_origin="https://app.stage.upyoke.com",
    )
    assert result.ok is (result_url == ENTRY_URL)
    if result.ok:
        assert result.evidence["visible_confirmation"] == "Machine connected"


def test_safari_waits_for_visible_confirmation_after_pressing_the_control():
    from yoke_harness.ssh_mac_browser_approval import _script

    script = "\n".join(_script(allowed_urls=[ENTRY_URL]))
    assert script.index("AXPress") < script.index("Machine connected")
    assert '"AXHeading", "AXStaticText"' in script
    assert '"AXWebArea"' in script
    assert 'return "approved_in_place|"' in script


@pytest.mark.parametrize("confirmed", [False, True])
def test_chromium_confirms_the_heading_on_the_exact_clicked_page(
    monkeypatch, confirmed
):
    from contextlib import nullcontext
    from yoke_harness import linux_desktop_chromium as browser

    expressions = []

    class Page:
        def __init__(self, _url):
            pass

        def call(self, _method, **kwargs):
            expressions.append(kwargs["expression"])
            return {
                "result": {"value": "pressed" if len(expressions) == 1 else confirmed}
            }

    monkeypatch.setattr(browser, "_port", lambda: 1234)
    monkeypatch.setattr(
        browser,
        "_pages",
        lambda _port: [
            {"id": "bound", "url": ENTRY_URL, "webSocketDebuggerUrl": "fixture"}
        ],
    )
    monkeypatch.setattr(browser, "urlopen", lambda *a, **k: nullcontext())
    monkeypatch.setattr(browser, "DevToolsPage", Page)
    monkeypatch.setattr(browser, "NAVIGATION_ATTEMPTS", 1)
    monkeypatch.setattr(browser.time, "sleep", lambda _seconds: None)
    result = browser.approve([ENTRY_URL], "Approve machine")
    assert result["state"] == (
        "approved_in_place" if confirmed else "approval_navigation_missing"
    )
    assert "location.href === " in expressions[1]
    assert ENTRY_URL in expressions[1]
    assert "getClientRects().length" in expressions[1]
