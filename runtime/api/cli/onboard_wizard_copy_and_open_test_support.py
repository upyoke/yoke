# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from contextlib import nullcontext

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

    def call_after_refresh(self, callback, *args):
        assert "Opening your browser…" in self.footer.rendered[-1]
        callback(*args)
