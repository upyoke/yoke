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
import json

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_wizard import (  # noqa: E402
    PROJECT_GITHUB_REUSE_MACHINE,
    WizardDefaults,
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
            await pilot.press("down")   # github: Skip for now (Connect is default)
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

    steps.reset_project_fields(result)

    assert result.existing_project_id is None
    assert result.existing_project_match_source is None
    assert result.existing_project_local_source is None


def test_cancel_at_finish_does_not_apply() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):  # project: move to machine-only
                await pilot.press("down")
            await pilot.press("enter")  # project: machine-only
            await pilot.press("down")   # finish: move to Cancel
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
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder (default, local-checkout)
            await type_text(pilot, "/home/code/widget")  # checkout path
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> widget
            await pilot.press("enter")  # name placeholder
            await pilot.press("down")   # publish prompt: move to No
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


def test_local_checkout_manifest_project_id_skips_project_setup(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            body = _body_text(app)
            assert title == "Existing Yoke project found."
            assert (
                "Local project metadata matched a Yoke core database project."
                in body
            )
            assert (
                "Local machine: found project id 37 in .yoke/install-manifest.json."
                in body
            )
            assert "Yoke core database: verified project id 37." in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"
    assert applied["project_name"] == "Buzz"
    assert len(app.result.board_art_variants) == 1


def test_stored_checkout_project_id_shows_confirmation_picker(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    checkout.mkdir()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"projects": {str(checkout): {"project_id": 37}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app(WizardDefaults(
        config_path=str(config),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.pause()
            assert "Use an existing project mapping?" in _body_text(app)
            assert str(checkout) in _body_text(app)
            await pilot.press("enter")  # stored mapping: reuse checkout
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            body = _body_text(app)
            assert title == "Existing Yoke project found."
            assert "Checkout:" in body
            assert (
                "Local project metadata matched a Yoke core database project."
                in body
            )
            assert "Local machine: found project id 37 in machine config." in body
            assert "Yoke core database: verified project id 37." in body
            assert str(checkout) in body
            assert "~/code/my-project" not in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_checkout"] == str(checkout)
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"
    assert applied["project_name"] == "Buzz"
    assert len(app.result.board_art_variants) == 1


def test_existing_project_with_board_art_skips_art_flow(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    (checkout / ".yoke" / "board-art").write_text("# art\n", encoding="utf-8")
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app(WizardDefaults(
        config_path=str(tmp_path / "config.json"),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            assert title == "Existing Yoke project found."
            await pilot.press("enter")  # continue -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert app.result.board_art_variants == []


def test_reuse_machine_pat_shares_token_with_project(monkeypatch) -> None:
    from yoke_cli.config import github_publish
    from yoke_cli.config import onboard_wizard_flow

    # Owner list is fetched behind a seam — patch it so no scenario hits GitHub.
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_publish.RepoOwner("octocat", "user")],
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # machine github: Connect a token (default)
            await type_text(pilot, "ghp_machinepat")
            await pilot.press("enter")
            await pilot.press("enter")  # GitHub verification success: Continue
            mode_index = next(
                i for i, r in enumerate(steps.MODE_ROWS)
                if r.value == onboard_project.PROJECT_MODE_CREATE_REPO
            )
            for _ in range(mode_index):
                await pilot.press("down")
            await pilot.press("enter")  # project mode: create-repo
            await type_text(pilot, "/home/code/demo")  # checkout
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> demo
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # publish: Yes — publish (preselected)
            await pilot.press("enter")  # owner picker: octocat (only row)
            await pilot.press("enter")  # repo name placeholder -> demo
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == PROJECT_GITHUB_REUSE_MACHINE
            )
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")  # project github: reuse machine PAT
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["machine_github_token"] == "ghp_machinepat"
    assert applied["project_github_token"] == "ghp_machinepat"
    assert applied["project_github_adoption"] == "store-token"
    assert applied["project_github_repo"] == "octocat/demo"
    publish = applied["project_publish"]
    assert publish is not None
    assert publish.owner == "octocat"
    assert publish.name == "demo"
    assert publish.user_login == "octocat"
    assert publish.token == "ghp_machinepat"
    assert publish.private is True


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
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            create_index = next(
                i for i, r in enumerate(steps.MODE_ROWS)
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
            await pilot.press("down")   # machine github: Skip for now
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
            await pilot.press("down")   # publish prompt: move to No
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
            await pilot.press("down")   # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):  # project: move to machine-only
                await pilot.press("down")
            await pilot.press("enter")  # project: machine-only
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    assert spy.applied is not None
    assert spy.applied["project_mode"] == onboard_project.PROJECT_MODE_MACHINE_ONLY


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )
