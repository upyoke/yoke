"""The copy and open keys hand out the exact string a screen is showing.

A one-time code and a sign-in URL are what onboarding asks a person to carry
into a browser, so the string that reaches the clipboard must be the one on
screen — byte for byte, no shortening and no re-wrapping.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.config import onboard_clipboard
from yoke_cli.config import onboard_wizard_copy_open as copy_open
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult
from yoke_cli.config.onboard_wizard_state import CopyTarget

LONG_URL = (
    "https://console.aws.amazon.com/cloudformation/home?region=us-east-1"
    "#/stacks/quickcreate?stackName=yoke-bootstrap&templateURL=https%3A%2F%2F"
    "example.test%2Ftemplates%2Fbootstrap.yaml&param_Purpose=onboarding"
)
CODE = "WDJB-MJHT"


class _FooterSpy:
    """The shell surface the flow touches: one footer widget it updates."""

    def __init__(self) -> None:
        self.rendered: list[str] = []

    def update(self, text: str) -> None:
        self.rendered.append(text)


class _Shell(copy_open.CopyOpenFlow):
    def __init__(self) -> None:
        self.footer = _FooterSpy()

    def query_one(self, _selector, _expect_type=None):
        return self.footer


def _completed(returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stderr=stderr)


def test_copy_shells_out_with_the_exact_string(monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], str]] = []

    def run(command, text):
        calls.append((tuple(command), text))
        return _completed()

    real_copy = onboard_clipboard.copy
    monkeypatch.setattr(
        onboard_clipboard,
        "copy",
        lambda value: real_copy(
            value,
            platform=onboard_clipboard.MACOS_PLATFORM,
            run=run,
            which=lambda name: f"/usr/bin/{name}",
        ),
    )
    shell = _Shell()
    shell._set_copy_targets([CopyTarget("the AWS stack link", LONG_URL, is_url=True)])

    shell.action_copy_target()

    assert calls == [(("pbcopy",), LONG_URL)]
    assert "Copied the AWS stack link." in shell.footer.rendered[-1]


def test_a_screen_with_a_code_and_a_url_offers_both(monkeypatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        onboard_clipboard,
        "copy",
        lambda value: (
            copied.append(value) or onboard_clipboard.ClipboardCopyResult(
                copied=True, command="pbcopy",
            )
        ),
    )
    shell = _Shell()
    shell._set_copy_targets(
        [
            CopyTarget("the one-time code", CODE),
            CopyTarget("the approval link", LONG_URL, is_url=True),
        ]
    )

    shell.action_copy_target()
    shell.action_copy_target()

    assert copied == [CODE, LONG_URL]


def test_a_failed_copy_says_why_instead_of_claiming_success(monkeypatch) -> None:
    monkeypatch.setattr(
        onboard_clipboard,
        "copy",
        lambda _value: onboard_clipboard.ClipboardCopyResult(
            copied=False, reason="pbcopy is not installed",
        ),
    )
    shell = _Shell()
    shell._set_copy_targets([CopyTarget("the one-time code", CODE)])

    shell.action_copy_target()

    note = shell.footer.rendered[-1]
    assert "Couldn't copy the one-time code" in note
    assert "pbcopy is not installed" in note


def test_open_hands_the_url_to_the_browser(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        copy_open,
        "open_url",
        lambda url: (
            opened.append(url) or BrowserOpenResult(opened=True, method="webbrowser")
        ),
    )
    shell = _Shell()
    shell._set_copy_targets(
        [
            CopyTarget("the one-time code", CODE),
            CopyTarget("the approval link", LONG_URL, is_url=True),
        ]
    )

    shell.action_open_target()

    assert opened == [LONG_URL]
    assert "Opened the approval link" in shell.footer.rendered[-1]


def test_keys_on_a_screen_with_nothing_to_carry_say_so() -> None:
    shell = _Shell()
    shell._set_copy_targets([])

    shell.action_copy_target()
    shell.action_open_target()

    assert copy_open.NOTHING_TO_COPY_NOTE in shell.footer.rendered[-2]
    assert copy_open.NOTHING_TO_OPEN_NOTE in shell.footer.rendered[-1]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (onboard_clipboard.MACOS_PLATFORM, "pbcopy"),
        ("linux", "wl-copy"),
    ],
)
def test_each_platform_uses_its_own_clipboard_command(platform, expected) -> None:
    calls: list[tuple[str, ...]] = []

    result = onboard_clipboard.copy(
        CODE,
        platform=platform,
        run=lambda command, text: (
            calls.append(tuple(command)) or _completed()
        ),
        which=lambda name: f"/usr/bin/{name}",
    )

    assert result.copied is True
    assert calls[0][0] == expected


def test_a_missing_clipboard_command_falls_through_to_the_next() -> None:
    calls: list[tuple[str, ...]] = []

    result = onboard_clipboard.copy(
        CODE,
        platform="linux",
        run=lambda command, text: (
            calls.append(tuple(command)) or _completed()
        ),
        which=lambda name: None if name == "wl-copy" else f"/usr/bin/{name}",
    )

    assert result.copied is True
    assert calls == [("xclip", "-selection", "clipboard")]
