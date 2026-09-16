"""Fixed-height Applying-screen progress coverage."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_applying_screen_updates_totals_and_current_operation() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {"plan": {"steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                {"action": "set-active-env", "target": "stage"},
            ]}}
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            assert str(app.query_one("#apply-overall").render()) == (
                "Overall: 0 of 2 complete"
            )
            app._set_apply_step_status(
                "create-or-validate-dir", "/home/.yoke", "running",
            )
            await pilot.pause()
            assert str(app.query_one("#apply-current").render()) == (
                "Current: Create your Yoke home folder at /home/.yoke"
            )
            app._set_apply_step_status(
                "create-or-validate-dir", "/home/.yoke", "done",
            )
            await pilot.pause()
            assert str(app.query_one("#apply-overall").render()) == (
                "Overall: 1 of 2 complete"
            )

    asyncio.run(scenario())


def test_applying_summary_needs_no_status_glyphs_in_plain_mode(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {"plan": {"steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
            ]}}
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            initial = str(app.query_one("#apply-overall").render())
            assert initial == "Overall: 0 of 1 complete"
            assert "○" not in initial
            app._set_apply_step_status(
                "create-or-validate-dir", "/home/.yoke", "done",
            )
            await pilot.pause()
            done = str(app.query_one("#apply-overall").render())
            assert done == "Overall: 1 of 1 complete"
            assert "✔" not in done

    asyncio.run(scenario())
