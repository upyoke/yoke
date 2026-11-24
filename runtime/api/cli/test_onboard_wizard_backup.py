"""Pilot proof that setup validates, waits for Apply, then offers restored projects."""

import asyncio

import pytest

pytest.importorskip("textual")
from textual.widgets import Static  # noqa: E402
from yoke_cli.config import onboard_backup as backup  # noqa: E402
from yoke_cli.config import existing_project_lookup as lookup  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_contracts.onboard_destinations import DESTINATION_LOCAL  # noqa: E402
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
    skip_hosting,
)
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402


def text(app):
    return " ".join(
        str(w.render()) for w in app.query("#onboard-body Static").results(Static)
    )


def test_local_backup_waits_for_apply_and_offers_projects(tmp_path, monkeypatch):
    stub_path_doctor(monkeypatch)
    calls = []
    monkeypatch.setattr(
        backup,
        "validate",
        lambda *a: (
            calls.append("validate")
            or {
                "archive": str(tmp_path / "backup.tar"),
                "receipt": {"org": "demo"},
                "ok": True,
                "receipt_verified": True,
                "sha256": "verified-dump",
            }
        ),
    )
    monkeypatch.setattr(backup, "restore_local", lambda *a: calls.append("import"))
    monkeypatch.setattr(
        backup, "projects", lambda *a: [{"id": 12, "slug": "demo", "name": "Demo"}]
    )
    app, spy = make_app(
        WizardDefaults(
            config_path=str(tmp_path / "config.json"), destination=DESTINATION_LOCAL
        )
    )
    checkout = tmp_path / "demo"
    checkout.mkdir()
    monkeypatch.setattr(
        lookup,
        "find_local_by_project_id",
        lambda **kwargs: lookup.ExistingProject(12, "demo", "Demo", "", "main", "DEMO"),
    )

    async def scenario():
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            assert "Start fresh" in text(app) and "Start from a backup" in text(app)
            await pilot.press("down", "enter")
            assert "Where is your backup?" in text(app)
            await type_text(pilot, str(tmp_path / "backup.tar"))
            await pilot.press("enter")
            await wait_for_view(pilot, "connect.backup_confirm", "SelectionList")
            assert "Start from this backup?" in text(app)
            assert "No name is needed" in text(app)
            assert calls == ["validate"]
            await pilot.press("enter")
            await wait_for_view(pilot, "github.machine", "SelectionList")
            assert calls == ["validate", "validate", "import"]
            await pilot.press("down", "enter")  # Skip GitHub
            await wait_for_view(pilot, "project.restored", "SelectionList")
            assert "Your backup's projects are ready." in text(app)
            assert "Demo" in text(app)
            assert spy.applied is None
            await pilot.press("enter")
            await wait_for_view(pilot, "project.restored_checkout", "Input")
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await wait_for_view(pilot, "project.existing_found", "SelectionList")
            assert "Existing project found: Demo." in text(app)
            await pilot.press("enter")
            await skip_hosting(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert spy.applied["existing_project_id"] == 12
            assert spy.applied["project_slug"] == "demo"

    asyncio.run(scenario())


def test_invalid_backup_never_offers_apply(tmp_path, monkeypatch):
    stub_path_doctor(monkeypatch)

    def invalid(*args):
        raise backup.BackupSetupError(
            "backup_invalid: checksum failed; choose another backup"
        )

    monkeypatch.setattr(backup, "validate", invalid)
    app, _ = make_app(
        WizardDefaults(
            config_path=str(tmp_path / "config.json"), destination=DESTINATION_LOCAL
        )
    )

    async def scenario():
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down", "enter")
            await type_text(pilot, "bad.tar")
            await pilot.press("enter")
            await wait_for_view(pilot, "connect.backup_failed", "SelectionList")
            assert "backup_invalid" in text(app)
            assert "Start from this backup?" not in text(app)
            # No backup file was kept, so the screen claims none was.
            assert "backup file is preserved" not in text(app)

    asyncio.run(scenario())
