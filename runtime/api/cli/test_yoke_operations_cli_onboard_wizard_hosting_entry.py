"""Live-wizard coverage for how the Hosting step takes the credential.

The access key id and its secret are one answer, so each key-entry screen carries
both boxes: these scenarios assert where the caret starts, that Enter walks the
boxes before it commits anything, that every control is reachable by keyboard,
and that a rejected value is marked on the box it came from and nowhere else.
Driven through the real ``OnboardWizardApp`` reading the live DOM.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import aws_admin_capability as hosting  # noqa: E402
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps  # noqa: E402

from runtime.api.cli.onboard_wizard_hosting_support import (  # noqa: E402,F401
    ACCESS_KEY_ID,
    SECRET_ACCESS_KEY,
    _isolated_machine_home,
    _stub_path_doctor,
    body_text,
    box,
    field_error,
    reach_aws_sign_in_screen,
    reach_credential_screen,
    seed_project,
    stub_identity,
)
from runtime.api.cli.onboard_wizard_test_helpers import make_app, type_text  # noqa: E402

# Typed character by character through the pilot, so these stay to keys a
# keyboard sends unshifted; the values themselves are shape-only to the wizard.
_TYPED_ACCESS_KEY = "akiatypedexample1234"
_TYPED_SECRET_ACCESS_KEY = "typed-secret-value-0987654321"


def test_aws_level_has_the_locked_default_and_supported_choices() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_aws_sign_in_screen(app, pilot)
            body = body_text(app)
            assert hosting_steps.HOSTING_AWS_SIGN_IN_TITLE in body
            assert "Create a dedicated deploy key" in body
            assert "Use existing credentials" in body
            assert "Not now" in body
            assert "Recommended" in body
            assert app.query_one("#onboard-body SelectionList").cursor == 0
            unsupported = ("role arn", "sso", "instance profile", "web identity")
            assert not any(term in body.lower() for term in unsupported)

    asyncio.run(scenario())


def test_only_guided_entry_shows_creation_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quick_create = "https://console.aws.example/quick-create"
    monkeypatch.setattr(hosting, "quick_create_url", lambda **_kwargs: quick_create)

    async def entry_body(*, guided: bool) -> str:
        app, _spy = make_app()
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot, guided=guided)
            return body_text(app)

    guided = asyncio.run(entry_body(guided=True))
    existing = asyncio.run(entry_body(guided=False))

    assert hosting_steps.HOSTING_GUIDED_KEY_SUBTITLE in guided
    assert quick_create in guided
    assert hosting_steps.HOSTING_EXISTING_KEY_SUBTITLE in existing
    assert quick_create not in existing
    assert hosting_steps.HOSTING_GUIDED_KEY_SUBTITLE not in existing


def test_guided_entry_teaches_recovery_when_no_safe_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hosting, "quick_create_url", lambda **_kwargs: None)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot, guided=True)
            body = body_text(app)
            assert hosting_steps.NO_LINK_RECOVERY_LINE in body
            assert "Open the one-click AWS link" not in body
            assert "Set up the dedicated AWS key" in body

    asyncio.run(scenario())


def test_both_boxes_are_on_one_screen_with_the_caret_in_the_first() -> None:
    """The pair is explained and collected in the same place."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            access = box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD)
            secret = box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD)
            assert access.password is False
            assert secret.password is True
            body = body_text(app)
            assert "Access key ID" in body
            assert "Secret access key" in body
            assert "Save & verify" in body
            # The first box owns the caret, so a paste lands without a click.
            assert access.has_focus

    asyncio.run(scenario())


def test_enter_walks_the_boxes_then_commits_the_pair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Enter finishes a box; Enter on the last one saves both values at once."""
    stub_identity(monkeypatch)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            await type_text(pilot, _TYPED_ACCESS_KEY)
            await pilot.press("enter")
            assert box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).has_focus
            # The first value survives the move rather than being submitted alone.
            assert box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value == (
                _TYPED_ACCESS_KEY
            )
            assert hosting_steps.HOSTING_GUIDED_KEY_TITLE in body_text(app)
            await type_text(pilot, _TYPED_SECRET_ACCESS_KEY)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "aws-admin saved" in body_text(app)

    asyncio.run(scenario())

    stored = tmp_path / ".yoke" / "secrets" / "capability-secrets" / "acme-app"
    stored = stored / hosting.CAPABILITY_TYPE
    assert (stored / hosting.ACCESS_KEY_ID_KEY).read_text().strip() == (
        _TYPED_ACCESS_KEY
    )
    assert (stored / hosting.SECRET_ACCESS_KEY_KEY).read_text().strip() == (
        _TYPED_SECRET_ACCESS_KEY
    )


def test_a_rejected_value_marks_only_the_box_it_came_from() -> None:
    """One bad box stops the save and says so where the caret goes back to."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            # A pasted pair rather than a single value: rejected, and the other
            # box is left alone.
            box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value = "AKIA1 AKIA2"
            box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).value = SECRET_ACCESS_KEY
            app._on_hosting_credential_choice("connect")
            await pilot.pause()
            assert "paste the access key ID alone" in field_error(
                app, hosting_steps.HOSTING_ACCESS_KEY_FIELD
            )
            assert field_error(app, hosting_steps.HOSTING_SECRET_KEY_FIELD) == ""
            assert box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).has_focus
            # Nothing was handed on: the screen still asks for the pair.
            assert hosting_steps.HOSTING_GUIDED_KEY_TITLE in body_text(app)
            assert app.result.hosting_verification is None

    asyncio.run(scenario())


def test_an_empty_second_box_is_marked_on_thatbox() -> None:
    """The check runs per box, so a missing secret never blames the key id."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value = ACCESS_KEY_ID
            app._on_hosting_credential_choice("connect")
            await pilot.pause()
            assert field_error(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD) == ""
            assert "Paste the secret access key." in field_error(
                app, hosting_steps.HOSTING_SECRET_KEY_FIELD
            )
            assert box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).has_focus

    asyncio.run(scenario())


def test_a_corrected_value_clears_the_mark_and_saves(monkeypatch) -> None:
    """Fixing the rejected box lets the same screen commit the pair."""
    stub_identity(monkeypatch)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            app._on_hosting_credential_choice("connect")  # both boxes still empty
            await pilot.pause()
            assert "Paste the access key ID." in field_error(
                app, hosting_steps.HOSTING_ACCESS_KEY_FIELD
            )
            box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value = ACCESS_KEY_ID
            box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).value = SECRET_ACCESS_KEY
            app._on_hosting_credential_choice("connect")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "aws-admin saved" in body_text(app)

    asyncio.run(scenario())


def test_tab_walks_the_boxes_and_the_rows_in_both_directions() -> None:
    """Every control on the screen is reachable without a mouse."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await reach_credential_screen(app, pilot)
            access = box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD)
            secret = box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD)
            rows = app.query_one("#onboard-body SelectionList")
            await pilot.press("tab")
            assert secret.has_focus
            await pilot.press("tab")
            assert rows.has_focus
            await pilot.press("shift+tab")
            assert secret.has_focus
            await pilot.press("shift+tab")
            assert access.has_focus

    asyncio.run(scenario())


def test_a_keystroke_during_the_swap_lands_in_the_firstbox() -> None:
    """A character typed before the boxes settle is not dropped."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            seed_project(app)
            app._goto_hosting()
            app._on_hosting_provider_choice("aws")
            app._on_hosting_aws_sign_in_choice("create-key")
            await pilot.press("a")
            await pilot.pause()
            assert box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value == "a"
            assert box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).value == ""

    asyncio.run(scenario())
