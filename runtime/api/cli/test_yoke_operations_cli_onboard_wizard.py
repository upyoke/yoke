"""Pilot-driven coverage for the full-screen ``yoke onboard`` wizard.

Tests drive the arrow-key flow and assert the field set the wizard hands to
``build_report``. ``build_report`` is spied at the wizard boundary so no real
machine or Yoke core database writes happen. Each scenario is an async coroutine
run under ``asyncio.run`` so the suite needs no async-test plugin. Shared pilot
scaffolding lives in ``onboard_wizard_test_helpers``; back-navigation cases live
in ``test_yoke_operations_cli_onboard_wizard_nav``.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_wizard import (  # noqa: E402
    WizardResult,
)
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    SelectionList,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_machine_only_flow_applies_machine_config() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # github: Skip for now (Connect is default)
            await pilot.press("enter")
            for _ in range(4):  # project: move to "Don't set up a project now"
                await pilot.press("down")
            await pilot.press("enter")  # project: machine-only
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_MACHINE_ONLY
    assert applied["env_name"] == "prod"
    assert applied["api_url"] == "https://api.test"
    assert applied["token"] == "actor-token"
    assert applied["machine_github_choice"] == onboard_machine_github.CHOICE_SKIP
    assert app.exit_code == 0
    assert app.cancelled is False


def test_reset_project_fields_clears_existing_project_match_state() -> None:
    result = WizardResult(
        config_path="/home/.yoke/config.json",
        env_name="prod",
        api_url="https://api.test",
    )
    result.existing_project_id = 37
    result.existing_project_match_source = (
        existing_project_lookup.MATCH_SOURCE_GITHUB_REPO
    )
    result.existing_project_local_source = "machine config"
    result.project_remote_url = "https://github.com/old/repo.git"
    result.project_checkout = "/tmp/old"
    result.project_github_repo = "old/repo"
    result.project_github_adoption = "app-binding"
    result.project_publish_to_github = True
    result.project_publish_owner = "old"
    result.project_publish_owner_login = "operator"
    result.project_publish_repo_name = "repo"
    result.project_publish_private = False
    result.project_clone_outcome = "fork"
    result.project_clone_keep_upstream = False
    result.project_clone_requires_machine_github = True
    result.project_source_default_branch = "release"
    result.project_keep_existing_remote = True

    steps.reset_project_fields(result)

    assert result.existing_project_id is None
    assert result.existing_project_match_source is None
    assert result.existing_project_local_source is None
    assert result.project_remote_url is None
    assert result.project_checkout is None
    assert result.project_github_repo is None
    assert result.project_github_adoption is None
    assert result.project_publish_to_github is False
    assert result.project_publish_owner is None
    assert result.project_publish_owner_login is None
    assert result.project_publish_repo_name is None
    assert result.project_publish_private is True
    assert result.project_clone_outcome is None
    assert result.project_clone_keep_upstream is True
    assert result.project_clone_requires_machine_github is False
    assert result.project_source_default_branch is None
    assert result.project_keep_existing_remote is False


def test_cancel_at_finish_does_not_apply() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):  # project: move to machine-only
                await pilot.press("down")
            await pilot.press("enter")  # project: machine-only
            await pilot.press("down")  # finish: move to Cancel
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    assert spy.applied is None
    assert app.cancelled is True
    assert app.exit_code == 0


def test_local_checkout_collects_project_fields() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press(
                "enter"
            )  # project: existing folder (default, local-checkout)
            await type_text(pilot, "/home/code/widget")  # checkout path
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> widget
            await pilot.press("enter")  # name placeholder
            await pilot.press("down")  # publish prompt: move to No
            await pilot.press("enter")  # publish: No — keep local
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # public item prefix placeholder
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    assert applied["project_checkout"] == "/home/code/widget"
    assert applied["project_slug"] == "widget"
    assert applied["project_name"] == "widget"
    assert applied["project_default_branch"] == "main"
    assert applied["project_public_item_prefix"] == "WIDG"


def test_keystrokes_during_transition_reach_the_new_input() -> None:
    """A key typed with no pause after a screen-transition Enter must land in the
    freshly mounted input — not be swallowed by the outgoing widget.

    The transition Enter (project mode -> "Name your new project folder") and the
    first character are pressed back to back, the way a fast typist starts a path
    before the new screen settles. The leading "~" of a home-relative path is the
    painful real case: losing it turns "~/proj" into a broken path. The body swap
    + focus now run synchronously inside the transition handler, so the new input
    owns focus before the next key is dispatched and the character is captured.

    Note (test honesty): the pilot serializes key events and the swap on one
    message loop, so it cannot reproduce the *raw-terminal* interleave where a
    keystroke arrives mid-transition; the operator verifies that on the live TUI.
    """
    app, _spy = make_app()

    async def scenario() -> None:
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            create_index = next(
                i
                for i, r in enumerate(steps.MODE_ROWS)
                if r.value == onboard_project.PROJECT_MODE_CREATE_REPO
            )
            for _ in range(create_index):
                await pilot.press("down")
            # Transition Enter and the first character back to back, no pause: the
            # transition lands on the "Name your new project folder" input.
            await pilot.press("enter")
            await pilot.press("~")
            await pilot.press("t")
            await pilot.press("e")
            await pilot.press("s")
            await pilot.press("t")
            await pilot.pause()
            field = app.query_one("#onboard-input", Input)
            assert field.disabled is False
            assert app.focused is field
            assert field.value == "~test"

    asyncio.run(scenario())


def test_fast_type_enter_type_across_inputs_collects_both_values() -> None:
    """A rapid type -> enter -> type sequence across two consecutive inputs must
    not collide in the widget registry — the regression the original deferral
    guarded against. Both input views reuse the id ``onboard-input``; awaiting
    the removal before mounting the next keeps the swap clean so the second value
    lands in the second input without dropping the first.
    """
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder (local-checkout)
            # First input: checkout path, typed fast then Enter.
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            # Second input (slug) immediately: replace the suggested value with
            # a custom one back to back, no pause.
            await pilot.press("ctrl+u")
            await type_text(pilot, "wdgt")
            await pilot.press("enter")  # slug submit
            await pilot.press("enter")  # name placeholder
            await pilot.press("down")  # publish prompt: move to No
            await pilot.press("enter")  # publish: No — keep local
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # public item prefix placeholder
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_checkout"] == "/home/code/widget"
    assert applied["project_slug"] == "wdgt"


def test_body_click_keeps_enter_live() -> None:
    """Clicking the non-focusable body must not silently disable Enter: on_click
    refocuses the active SelectionList so the row's Enter binding stays live."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.pause()
            await pilot.click("#onboard-body")  # would clear focus without the fix
            await pilot.pause()
            assert isinstance(app.focused, SelectionList)
            await pilot.press("down")  # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):  # project: move to machine-only
                await pilot.press("down")
            await pilot.press("enter")  # project: machine-only
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    assert spy.applied is not None
    assert spy.applied["project_mode"] == onboard_project.PROJECT_MODE_MACHINE_ONLY
