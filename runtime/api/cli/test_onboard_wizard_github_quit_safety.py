"""Quit suppression while a machine GitHub mutation is in flight."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import make_app  # noqa: E402


def test_ctrl_c_suppressed_during_github_machine_mutation() -> None:
    app, _spy = make_app()
    app._checking_blocks_quit = True

    app.action_quit_wizard()

    assert app.cancelled is False
