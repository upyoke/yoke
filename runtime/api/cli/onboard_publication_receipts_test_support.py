# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from yoke_contracts.git_hook_markers import HEAD_RECORDING_SKIP_ENV

from yoke_cli.config import (
    onboard_apply_report,
    onboard_publication_receipts as receipts,
)

from yoke_cli.config import project_publication_destination as destination

from yoke_cli.project_install import publication, runner

from yoke_cli.config import onboard_wizard_board_art_apply

from runtime.api.cli.project_install_publication_test_support import (
    bind_bundle,
    git,
    remote_world,
)


def setup_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv(HEAD_RECORDING_SKIP_ENV, "1")
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    from yoke_cli.project_install import harness_machine_persist

    monkeypatch.setattr(
        harness_machine_persist, "persist_install_glue", lambda *args: None
    )
    monkeypatch.setattr(runner, "sync_local_snapshot_for_write", lambda **kwargs: {})
    writer = onboard_apply_report.ApplyReportWriter.start(
        {},
        {
            "project_checkout": str(world.checkout),
            "env_name": "test",
            "project_default_branch": "main",
            "config_path": str(tmp_path / "config.json"),
        },
    )
    from runtime.api.cli.project_publication_settings_test_support import (
        seed_project,
    )

    seed_project(world.checkout)
    destination.prevent_push(world.checkout)
    with receipts.recording(writer):
        install = runner.install(world.checkout, project_id=7)
    art = world.checkout / ".yoke/board-art"
    art.write_text("generated art\n")
    art_commit = onboard_wizard_board_art_apply.commit_board_art(
        world.checkout,
        {
            "apply_report": writer.summary(),
            "project_onboarding": {"install": install},
        },
    )["commit"]
    writer.payload = json.loads(writer.path.read_text())
    return world, writer, install, art_commit
