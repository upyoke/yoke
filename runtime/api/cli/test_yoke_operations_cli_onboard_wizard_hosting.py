"""Live-wizard coverage for what the Hosting step does with a credential.

Skipping strands nothing, a saved pair actually lands on disk owner-only, and
each failure ends on a screen that says which of the three things went wrong.
Driven through the real ``OnboardWizardApp`` reading the live DOM; the AWS CLI
is never invoked. How the connect screen takes the pair in the first place lives
in the entry suite beside this one.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")

from yoke_cli.config import aws_admin_capability as hosting  # noqa: E402
from yoke_contracts import hosting_posture  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402

from runtime.api.cli.onboard_wizard_hosting_support import (  # noqa: E402,F401
    ACCESS_KEY_ID,
    IDENTITY_JSON,
    SECRET_ACCESS_KEY,
    _isolated_machine_home,
    _stub_path_doctor,
    body_text,
    drive,
    paste_credentials,
    seed_project,
    stub_probe,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    skip_hosting,
    type_text,
)


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def test_skip_reaches_review_and_plans_the_skip() -> None:
    """Declining hosting continues to Review and reports the skipped answer."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("down")   # publish: No
            await pilot.press("enter")
            await pilot.press("enter")  # default branch
            await pilot.press("enter")  # prefix
            await complete_board_art(pilot)
            assert "Connect your hosting provider?" in body_text(app)
            await skip_hosting(pilot)
            assert "Review what" in body_text(app)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["hosting_choice"] == hosting_posture.POSTURE_UNDECIDED


def test_run_without_a_deployable_project_never_asks() -> None:
    """Machine-only onboarding has no project to own a credential."""
    app, _spy = make_app()

    async def action(a: Any, _pilot: Any) -> None:
        a.result.project_mode = onboard_project.PROJECT_MODE_MACHINE_ONLY
        a.result.project_slug = None
        a._goto_hosting()

    assert "Connect your hosting provider?" not in drive(app, action)
    assert app.result.hosting_choice == hosting_posture.POSTURE_UNDECIDED


def test_developing_yoke_itself_never_asks() -> None:
    """The Yoke source checkout deploys nothing of its own."""
    app, _spy = make_app()

    async def action(a: Any, _pilot: Any) -> None:
        a.result.project_mode = onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
        a.result.project_slug = "yoke"
        a._goto_hosting()

    assert "Connect your hosting provider?" not in drive(app, action)


# --------------------------------------------------------------------------- #
# Save and verify
# --------------------------------------------------------------------------- #


def test_save_and_verify_stores_both_values_and_shows_redacted_evidence(
    monkeypatch, tmp_path: Path,
) -> None:
    stub_probe(monkeypatch, stdout=IDENTITY_JSON)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)

    body = drive(app, action)

    stored = tmp_path / ".yoke" / "secrets" / "capability-secrets" / "acme-app"
    stored = stored / hosting.CAPABILITY_TYPE
    assert (stored / hosting.ACCESS_KEY_ID_KEY).read_text().strip() == ACCESS_KEY_ID
    assert (
        (stored / hosting.SECRET_ACCESS_KEY_KEY).read_text().strip()
        == SECRET_ACCESS_KEY
    )
    # Owner-only, both files and the directory that holds them.
    assert (stored / hosting.SECRET_ACCESS_KEY_KEY).stat().st_mode & 0o077 == 0
    assert stored.stat().st_mode & 0o077 == 0

    assert "aws-admin saved" in body
    assert "123456789012" in body
    assert "yoke-aws-admin" in body
    # Evidence, never echo: the secret must not reach any screen.
    assert SECRET_ACCESS_KEY not in body
    assert app.result.hosting_choice == hosting_posture.POSTURE_YOKE_MANAGED_AWS
    assert app.result.hosting_verification["account"] == "123456789012"


def test_rejected_credential_offers_reentry(monkeypatch) -> None:
    stub_probe(
        monkeypatch,
        code=255,
        stderr="An error occurred (InvalidClientTokenId) ... is invalid.",
    )
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "AWS rejected the hosting credential." in body
    assert "InvalidClientTokenId" in body
    assert "Re-enter the two values" in body
    # An unproven credential is not reported as connected.
    assert app.result.hosting_choice == hosting_posture.POSTURE_UNDECIDED


def test_absent_aws_cli_offers_keeping_the_saved_pair(monkeypatch) -> None:
    def _missing(_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "aws")

    monkeypatch.setattr(subprocess, "run", _missing)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Saved, but Yoke can't verify it here." in body
    assert "AWS CLI is not on PATH" in body
    assert "Keep it without verifying" in body


def test_keeping_an_unverified_pair_continues_as_connected(monkeypatch) -> None:
    def _missing(_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "aws")

    monkeypatch.setattr(subprocess, "run", _missing)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)
        await app.workers.wait_for_complete()
        a._on_hosting_error_choice("keep")

    drive(app, action)

    assert app.result.hosting_choice == hosting_posture.POSTURE_YOKE_MANAGED_AWS
    # Kept without proof, so no verification evidence is claimed.
    assert app.result.hosting_verification is None


def test_failed_store_reports_the_write_not_the_credential(monkeypatch) -> None:
    """A failed write must not be reported as AWS rejecting the credential."""

    def _refuse(*_args, **_kwargs):
        raise hosting.HostingCredentialError("secrets directory is not writable")

    monkeypatch.setattr(hosting, "store_credential", _refuse)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Couldn't save the hosting credential." in body
    assert "AWS rejected" not in body
    assert "not writable" in body


def test_unexpected_failure_is_not_blamed_on_aws(monkeypatch) -> None:
    """A failure that is not AWS's verdict never claims that it is."""

    def _boom(*_args, **_kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(hosting, "store_credential", _boom)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        seed_project(a)
        a._goto_hosting()
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Couldn't save the hosting credential." in body
    assert "AWS rejected" not in body
