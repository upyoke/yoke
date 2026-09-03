"""Live-wizard coverage for what the Hosting step does with a credential.

Skipping strands nothing, a saved pair actually lands on disk owner-only, and
each failure says whether storage or identity verification failed. Driven
through the real ``OnboardWizardApp`` reading the live DOM; the AWS CLI is
never invoked. Keyboard behavior for the key-entry screens lives in the entry
suite beside this one.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")

from yoke_cli.config import aws_admin_capability as hosting  # noqa: E402
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps  # noqa: E402
from yoke_cli.config import onboard_wizard_hosting_prerequisite as prerequisite  # noqa: E402
from yoke_contracts import hosting_posture  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402

from runtime.api.cli.onboard_wizard_hosting_support import (  # noqa: E402,F401
    ACCESS_KEY_ID,
    SECRET_ACCESS_KEY,
    _aws_cli_present,
    _isolated_machine_home,
    _stub_path_doctor,
    body_text,
    drive,
    paste_credentials,
    reach_credential_screen,
    reach_provider_screen,
    stub_aws_cli,
    stub_aws_cli_missing,
    stub_identity,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    skip_hosting,
    submit_public_item_prefix,
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
            await submit_public_item_prefix(pilot)
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


@pytest.mark.parametrize("guided", [True, False], ids=["guided", "existing"])
def test_both_key_paths_store_and_verify_the_same_redacted_identity(
    monkeypatch,
    tmp_path: Path,
    guided: bool,
) -> None:
    stub_identity(monkeypatch)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_credential_screen(a, pilot, guided=guided)
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
    stub_identity(
        monkeypatch,
        failure=hosting.HostingVerificationError(
            "Yoke could not verify the AWS credentials (InvalidClientTokenId)."
        ),
    )
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_credential_screen(a, pilot)
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Yoke couldn't verify the AWS credential." in body
    assert "InvalidClientTokenId" in body
    assert "Re-enter the two values" in body
    assert "Not now" in body
    assert SECRET_ACCESS_KEY not in body
    # An unproven credential is not reported as connected.
    assert app.result.hosting_choice == hosting_posture.POSTURE_UNDECIDED


def test_network_failure_offers_reentry_or_not_now_without_secrets(monkeypatch) -> None:
    stub_identity(
        monkeypatch,
        failure=hosting.HostingVerificationError(
            "Yoke could not verify the AWS credentials (NetworkUnavailable)."
        ),
    )
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_credential_screen(a, pilot, guided=False)
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Yoke couldn't verify the AWS credential." in body
    assert "NetworkUnavailable" in body
    assert "Re-enter the two values" in body
    assert "Not now" in body
    assert ACCESS_KEY_ID not in body
    assert SECRET_ACCESS_KEY not in body
    assert app.result.hosting_verification is None


def test_failed_store_reports_the_write_not_the_credential(monkeypatch) -> None:
    """A failed write must not be reported as AWS rejecting the credential."""

    def _refuse(*_args, **_kwargs):
        raise hosting.HostingCredentialError("secrets directory is not writable")

    monkeypatch.setattr(hosting, "store_credential", _refuse)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_credential_screen(a, pilot)
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Couldn't save the hosting credential." in body
    assert "couldn't verify" not in body
    assert "not writable" in body
    assert "Not now" in body


def test_unexpected_failure_is_not_blamed_on_aws(monkeypatch) -> None:
    """A failure that is not AWS's verdict never claims that it is."""

    def _boom(*_args, **_kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(hosting, "store_credential", _boom)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await reach_credential_screen(a, pilot)
        await paste_credentials(a, pilot)

    body = drive(app, action)
    assert "Couldn't save the hosting credential." in body
    assert "couldn't verify" not in body


# --------------------------------------------------------------------------- #
# The AWS CLI prerequisite
# --------------------------------------------------------------------------- #


async def _choose_aws(a: Any, pilot: Any) -> None:
    await reach_provider_screen(a, pilot)
    a._on_hosting_provider_choice("aws")
    await a.workers.wait_for_complete()
    await pilot.pause()


def test_missing_aws_cli_refuses_before_asking_for_a_key(monkeypatch) -> None:
    """A machine that cannot run the AWS CLI is told so, not asked for a key."""
    stub_aws_cli_missing(
        monkeypatch,
        detail_lines=("Install it: sudo installer -pkg AWSCLIV2.pkg -target /",),
    )
    app, _spy = make_app()

    body = drive(app, _choose_aws)

    assert hosting_steps.HOSTING_PREREQUISITE_TITLE in body
    assert "not installed on this machine" in body
    assert "AWSCLIV2.pkg" in body
    # The credential screens are not reachable from a refused prerequisite.
    assert "Access key ID" not in body
    assert hosting_steps.HOSTING_AWS_SIGN_IN_TITLE not in body
    # Nothing was saved and nothing was verified.
    assert "aws-admin saved" not in body
    assert app.result.hosting_verification is None
    assert not hosting.credential_saved("acme-app")


def test_refused_prerequisite_keeps_the_aws_answer_available(monkeypatch) -> None:
    """Installing the CLI and checking again continues into AWS, not around it."""
    stub_aws_cli_missing(monkeypatch)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await _choose_aws(a, pilot)
        # The operator installs the AWS CLI, then takes "Check again".
        stub_aws_cli(monkeypatch)
        prerequisite.on_refusal_choice(a, "retry")
        await a.workers.wait_for_complete()
        await pilot.pause()

    body = drive(app, action)
    assert hosting_steps.HOSTING_AWS_SIGN_IN_TITLE in body


def test_refused_prerequisite_leaves_hosting_undecided_only_by_choice(
    monkeypatch,
) -> None:
    """"Not now" is a decision the operator makes, and it stores no posture."""
    stub_aws_cli_missing(monkeypatch)
    app, _spy = make_app()

    async def action(a: Any, pilot: Any) -> None:
        await _choose_aws(a, pilot)
        prerequisite.on_refusal_choice(a, "skip")
        await pilot.pause()

    drive(app, action)

    assert app.result.hosting_choice == hosting_posture.POSTURE_UNDECIDED
    assert app.result.hosting_verification is None
