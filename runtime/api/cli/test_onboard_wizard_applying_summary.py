"""Applying-screen totals, individual rows and terminal status coverage."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_applying_screen_updates_totals_and_current_operation(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "0")
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {
                "plan": {
                    "steps": [
                        {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                        {"action": "set-active-env", "target": "stage"},
                    ]
                }
            }
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            assert str(app.query_one("#apply-overall").render()) == (
                "Overall: 0 of 2 complete"
            )
            assert str(app.query_one("#apply-step-0").render()).startswith("  ○ ")
            assert str(app.query_one("#apply-step-1").render()).startswith("  ○ ")
            app._set_apply_step_status(
                "create-or-validate-dir",
                "/home/.yoke",
                "running",
            )
            await pilot.pause()
            assert str(app.query_one("#apply-step-0").render()).startswith("  ◐ ")
            assert str(app.query_one("#apply-current").render()) == (
                "Current: Create your Yoke home folder at /home/.yoke"
            )
            app._set_apply_step_status(
                "create-or-validate-dir",
                "/home/.yoke",
                "done",
            )
            await pilot.pause()
            assert str(app.query_one("#apply-overall").render()) == (
                "Overall: 1 of 2 complete"
            )
            assert str(app.query_one("#apply-step-0").render()).startswith("  ✔ ")
            app._set_apply_step_status("set-active-env", "stage", "skipped")
            assert str(app.query_one("#apply-step-1").render()).startswith("  ⊘ ")
            app._set_apply_step_status("set-active-env", "stage", "failed")
            assert str(app.query_one("#apply-step-1").render()).startswith("  ✗ ")

    asyncio.run(scenario())


def test_applying_rows_use_ascii_marks_in_plain_mode(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "1")
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._review_plan = {
                "plan": {
                    "steps": [
                        {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                    ]
                }
            }
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await pilot.pause()
            initial = str(app.query_one("#apply-overall").render())
            assert initial == "Overall: 0 of 1 complete"
            assert "○" not in initial
            assert str(app.query_one("#apply-step-0").render()).startswith("  o ")
            app._set_apply_step_status(
                "create-or-validate-dir",
                "/home/.yoke",
                "done",
            )
            await pilot.pause()
            done = str(app.query_one("#apply-overall").render())
            assert done == "Overall: 1 of 1 complete"
            assert "✔" not in done
            assert str(app.query_one("#apply-step-0").render()).startswith("  + ")

    asyncio.run(scenario())


@pytest.fixture(scope="module")
def cpu_load():
    worker = subprocess.Popen([sys.executable, "-c", "while True: pass"])
    try:
        yield
    finally:
        worker.terminate()
        worker.wait(timeout=10)


@pytest.mark.parametrize("_attempt", range(200))
def test_applying_follows_the_running_row_and_keeps_distinct_targets(
    monkeypatch, cpu_load, _attempt
):
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "0")
    app, _spy = make_app()
    app.animation_level = "none"

    async def scenario():
        async with app.run_test(size=(80, 24)) as pilot:
            app._review_plan = {
                "plan": {
                    "steps": [
                        {
                            "action": "create-or-validate-dir",
                            "target": f"/folder/{index}",
                        }
                        for index in range(30)
                    ]
                }
            }
            app._apply_steps = app._applying_step_model()
            app._goto_applying()
            await app._apply_pending_swap()
            app._set_apply_step_status(
                "create-or-validate-dir", "/folder/29", "running"
            )
            refreshed = asyncio.Event()
            app.call_after_refresh(refreshed.set)
            await refreshed.wait()
            await pilot.pause()
            assert str(app.query_one("#apply-step-0").render()).startswith("  ○ ")
            assert str(app.query_one("#apply-step-29").render()).startswith("  ◐ ")
            body = app.query_one("#onboard-body")
            assert body.scroll_y > 0
            assert app.query_one("#apply-step-29").region.overlaps(body.content_region)
            app._set_apply_step_status("create-or-validate-dir", "/folder/0", "failed")
            refreshed.clear()
            app.call_after_refresh(refreshed.set)
            await refreshed.wait()
            await pilot.pause()
            assert app.query_one("#apply-step-0").region.overlaps(body.content_region)
            app._set_apply_step_status("create-or-validate-dir", "/folder/29", "done")
            app._render_current()
            await pilot.pause()
            assert str(app.query_one("#apply-step-29").render()).startswith("  ✔ ")

    asyncio.run(scenario())
