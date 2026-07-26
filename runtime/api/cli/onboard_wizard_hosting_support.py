"""Shared scaffolding for the Hosting-step wizard suites.

The Hosting scenarios split across sibling modules — how the connect screen
takes the credential, and what the step does with it once it has one — so this
module holds what both need: the isolation fixtures that keep every secret write
inside a temp home, the stubbed AWS identity probe, and the small readers that
drive the live app and inspect the screen it lands on.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from textual.widgets import Input, Static

from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps

from runtime.api.cli.onboard_wizard_test_helpers import stub_path_doctor

ACCESS_KEY_ID = "AKIAEXAMPLEEXAMPLE12"
SECRET_ACCESS_KEY = "wJalrXUtnFEMI-EXAMPLE-KEY-VALUE-abcd1234"
IDENTITY_JSON = (
    '{"UserId": "AIDAEXAMPLE", "Account": "123456789012", '
    '"Arn": "arn:aws:iam::123456789012:user/yoke-aws-admin"}'
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


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


async def reach_connect_screen(app, pilot) -> None:
    """Settle the front screen, then open the Hosting connect screen."""
    await pilot.pause()
    await app.workers.wait_for_complete()
    seed_project(app)
    app._goto_hosting()
    await pilot.pause()


async def paste_credentials(
    app,
    pilot,
    *,
    access_key_id: str = ACCESS_KEY_ID,
    secret_access_key: str = SECRET_ACCESS_KEY,
) -> None:
    """Fill both boxes on the connect screen and take "Save & verify"."""
    await pilot.pause()
    box(app, hosting_steps.HOSTING_ACCESS_KEY_FIELD).value = access_key_id
    box(app, hosting_steps.HOSTING_SECRET_KEY_FIELD).value = secret_access_key
    app._on_hosting_choice("connect")


def stub_probe(monkeypatch, *, stdout: str = "", stderr: str = "", code: int = 0):
    def _run(args, **_kwargs):
        assert args[:2] == ["aws", "sts"]
        return subprocess.CompletedProcess(args, code, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", _run)


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
