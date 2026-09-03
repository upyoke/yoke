"""Shared scaffolding for the Hosting-step wizard suites.

The Hosting scenarios split across sibling modules, so this module holds what
both need: isolated machine-secret custody, a redacted identity seam, and small
drivers for the provider, AWS sign-in, and credential-entry levels.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from textual.widgets import Input, Static

from yoke_cli.config import aws_admin_capability as hosting
from yoke_cli.config import aws_cli_prerequisite
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps

from runtime.api.cli.onboard_wizard_test_helpers import stub_path_doctor

ACCESS_KEY_ID = "AKIAEXAMPLEEXAMPLE12"
SECRET_ACCESS_KEY = "wJalrXUtnFEMI-EXAMPLE-KEY-VALUE-abcd1234"
ACCOUNT = "123456789012"
IDENTITY = "yoke-aws-admin"


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _aws_cli_present(monkeypatch):
    """Every scenario runs as if the machine has a working AWS CLI.

    The AWS branch preflights the executable before it asks for anything, so
    without this the suite would assert the credential screens on a machine
    that has the CLI and the prerequisite refusal on one that does not. The
    refusal itself is driven explicitly by :func:`stub_aws_cli_missing`.
    """
    stub_aws_cli(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path: Path):
    """Point every secret write at a temp home, never the operator's own."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))
    # The credential resolver hands ambient CI credentials authority when it
    # sees GitHub Actions; these scenarios are always about the machine store.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def body_text(app) -> str:
    return " ".join(
        str(w.render()) for w in app.query("#onboard-body Static").results(Static)
    )


def seed_project(app) -> None:
    app.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO
    app.result.project_slug = "acme-app"
    app.result.project_name = "Acme App"


def box(app, field) -> Input:
    return app.query_one(f"#{field.input_id}", Input)


def field_error(app, field) -> str:
    return str(app.query_one(f"#{field.error_id}", Static).render())


async def reach_provider_screen(app, pilot) -> None:
    """Settle the front screen, then open the provider-level choice."""
    await pilot.pause()
    await app.workers.wait_for_complete()
    seed_project(app)
    app._goto_hosting()
    await pilot.pause()


async def reach_aws_sign_in_screen(app, pilot) -> None:
    """Open the AWS-only sign-in choice from the provider level.

    Choosing AWS runs the CLI preflight on a worker thread, so the wait is what
    makes the screen under test the screen that is up when this returns.
    """
    await reach_provider_screen(app, pilot)
    app._on_hosting_provider_choice("aws")
    await app.workers.wait_for_complete()
    await pilot.pause()


async def reach_credential_screen(app, pilot, *, guided: bool = True) -> None:
    """Open guided or existing-key entry through both choice levels."""
    await reach_aws_sign_in_screen(app, pilot)
    app._on_hosting_aws_sign_in_choice(
        "create-key" if guided else "existing-key"
    )
    await pilot.pause()


async def paste_credentials(
    app,
    pilot,
    *,
    access_key_id: str = ACCESS_KEY_ID,
    secret_access_key: str = SECRET_ACCESS_KEY,
) -> None:
    """Fill both credential boxes and take "Save & verify"."""
    await pilot.pause()
    box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value = access_key_id
    box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).value = secret_access_key
    app._on_hosting_credential_choice("connect")


def stub_aws_cli(
    monkeypatch,
    *,
    executable: str = "/usr/local/bin/aws",
    version: str = "aws-cli/2.0.0",
) -> None:
    """Report a working AWS CLI without running one."""
    monkeypatch.setattr(
        aws_cli_prerequisite,
        "check_aws_cli",
        lambda: aws_cli_prerequisite.AwsCli(
            executable=executable, version=version,
        ),
    )


def stub_aws_cli_missing(
    monkeypatch,
    *,
    code: str = "aws-cli-missing",
    message: str = "The AWS CLI is not installed on this machine.",
    detail_lines: tuple[str, ...] = ("Install it: <installer command>",),
) -> None:
    """Refuse the AWS CLI preflight the way a clean host does."""
    def _check():
        raise aws_cli_prerequisite.AwsCliPrerequisiteError(
            code, message, detail_lines,
        )

    monkeypatch.setattr(aws_cli_prerequisite, "check_aws_cli", _check)


def stub_identity(
    monkeypatch,
    *,
    account: str = ACCOUNT,
    identity: str = IDENTITY,
    failure: BaseException | None = None,
) -> None:
    """Replace the facade seam; no SDK, executable, or real secret is used."""
    def _verify(_project_slug: str, _region: str) -> hosting.CallerIdentity:
        if failure is not None:
            raise failure
        return hosting.CallerIdentity(account=account, identity=identity)

    monkeypatch.setattr(hosting, "verify_caller_identity", _verify)


def drive(app, action) -> str:
    """Run ``action`` against the live app, returning the screen it lands on.

    The body text is read inside the pilot context: once ``run_test`` exits the
    app is torn down and every query returns nothing.
    """

    async def scenario() -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await action(app, pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            return body_text(app)

    return asyncio.run(scenario())
