# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Rule, Static  # noqa: E402

from textual.containers import VerticalScroll  # noqa: E402

from yoke_cli import main as yoke_operations_cli  # noqa: E402

from yoke_cli.config import path_doctor  # noqa: E402

from yoke_cli.config.onboard_terminal import plain_text  # noqa: E402

from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402

from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_INSTALL,
    STEPPER_ORDER,
    Stepper,
)


def _diagnosis(*, needs_fix: bool) -> path_doctor.PathDiagnosis:
    resolved = [
        path_doctor.ToolResolution(t, None if needs_fix else f"/bin/{t}")
        for t in path_doctor.TOOLS
    ]
    return path_doctor.PathDiagnosis(
        current_shell="zsh",
        tool_bin_dir="/home/u/.local/bin",
        current_on_path=not needs_fix,
        current_resolved=resolved,
        startup_file="/home/u/.zprofile",
        future_adds_bin=not needs_fix,
        managed_block_present=not needs_fix,
        future_resolved=resolved,
        needs_fix=needs_fix,
        ssh_startup_file="/home/u/.zshenv",
        ssh_adds_bin=not needs_fix,
        ssh_managed_block_present=not needs_fix,
        ssh_resolved=resolved,
        ssh_needs_fix=needs_fix,
        login_needs_fix=needs_fix,
        managed_path_dirs=("/home/u/.local/bin",),
    )
