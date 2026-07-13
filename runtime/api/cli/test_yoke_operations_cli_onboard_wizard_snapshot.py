"""Smoke-render the Project-step wizard screen and assert it produces an SVG.

A render check only: it must NOT write any tracked source file. It used to write
a committed ``onboard_wizard_preview.svg`` on every run, but Textual embeds a
non-deterministic terminal id, so each run mutated tracked source and dirtied
the working tree. The committed artifact was deleted and the write removed; a
visual-preview artifact, if wanted, belongs in a deliberate render entrypoint,
not a pytest side effect. Run under textual; skipped when textual is unavailable.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import path_doctor  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from runtime.api.cli.onboard_wizard_golden_support import golden_color_env  # noqa: E402


def _all_clear_diagnosis() -> path_doctor.PathDiagnosis:
    resolved = [path_doctor.ToolResolution(t, f"/bin/{t}") for t in path_doctor.TOOLS]
    return path_doctor.PathDiagnosis(
        current_shell="zsh",
        tool_bin_dir="/home/u/.local/bin",
        current_on_path=True,
        current_resolved=resolved,
        startup_file="/home/u/.zprofile",
        future_adds_bin=True,
        managed_block_present=True,
        future_resolved=resolved,
        needs_fix=False,
    )


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _all_clear_diagnosis())
    monkeypatch.setattr(
        path_doctor, "verify_fresh_login",
        lambda shell=None: _all_clear_diagnosis().future_resolved,
    )


def test_project_step_renders() -> None:
    def _noop_report(_kwargs: dict) -> dict:
        return {"plan": {"steps": []}}

    with golden_color_env():
        app = OnboardWizardApp(
            defaults=WizardDefaults(
                config_path="/tmp/cfg.json", env_name="prod",
                api_url="https://yoke.example.test", token="actor-token",
            ),
            apply_report=_noop_report,
        )

    async def scenario() -> str:
        from yoke_cli.config.onboard_wizard_widgets import (
            STEP_PROJECT,
            SelectionList,
            Stepper,
        )

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Clear the front PATH step (all-clear Continue) and the machine
            # GitHub step (skip), then land on the project-source step and
            # select "Create a new project".
            await pilot.press("enter")  # path: continue
            await pilot.pause()
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")   # project: move to "Create a new project"
            await pilot.press("down")
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            assert selection.selected_value == "create-repo"
            return app.export_screenshot(title="yoke onboard · Project")

    with golden_color_env():
        svg = asyncio.run(scenario())
    # The SVG renders each glyph as a positioned <text> run, so the body words
    # are not contiguous substrings; assert structure instead.
    assert svg.startswith("<svg")
    assert "rich-terminal" in svg
