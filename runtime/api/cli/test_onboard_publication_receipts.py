"""Read-only setup can later publish its own history, never authored ancestors."""

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


@pytest.fixture(autouse=True)
def isolated_machine(tmp_path, monkeypatch):
    monkeypatch.setenv(HEAD_RECORDING_SKIP_ENV, "1")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def setup_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv(HEAD_RECORDING_SKIP_ENV, "1")
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    from yoke_cli.project_install import harness_machine_persist

    monkeypatch.setattr(harness_machine_persist, "persist_install_glue", lambda *args: None)
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
    from runtime.api.cli.test_project_publication_settings import seed_project

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


def test_fresh_writable_setup_publishes_receipted_install_and_art(
    tmp_path, monkeypatch
):
    world, writer, install, art = setup_read_only(tmp_path, monkeypatch)
    before = world.remote_tip()
    assert len(writer.payload["created_commits"]) == 2
    assert set(receipts.verified_commits(world.checkout, "main")) == {
        install["commit"]["sha"],
        art["sha"],
    }
    assert world.remote_tip() == before
    destination.allow_source_push(world.checkout)
    # A fresh run has nothing new to commit; prior generated history still belongs to setup.
    result = publication.publish_onboarded_layer(
        world.checkout,
        {
            **install,
            "commit": {"status": "nothing_to_commit"},
        },
        default_branch="main",
    )
    assert result["status"] == "published"
    assert world.remote_tip() == art["sha"]


def test_publication_head_is_not_creation_proof(tmp_path, monkeypatch):
    world, writer, install, _ = setup_read_only(tmp_path, monkeypatch)
    before = world.remote_tip()
    (world.checkout / "private.txt").write_text("unrelated authored work\n")
    git(world.checkout, "add", "private.txt")
    git(world.checkout, "commit", "-qm", "Authored change")
    authored = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    writer.payload["steps"] = [
        {"detail": {"commit": authored, "status": "publication-pending"}}
    ]
    writer.write()
    receipts.record_created(
        world.checkout, {"sha": authored, "status": "nothing_to_commit"}, writer=writer
    )
    assert authored not in receipts.verified_commits(world.checkout, "main")
    destination.allow_source_push(world.checkout)
    result = publication.publish_onboarded_layer(
        world.checkout,
        {
            **install,
            "commit": {"status": "nothing_to_commit"},
        },
        default_branch="main",
    )
    assert result["status"] == "publication_pending"
    assert world.remote_tip() == before


@pytest.mark.parametrize(
    "change", ["branch", "source", "project", "identity", "permissions"]
)
def test_receipts_do_not_cross_binding_or_private_file_boundary(
    tmp_path, monkeypatch, change
):
    world, writer, _, _ = setup_read_only(tmp_path, monkeypatch)
    assert receipts.verified_commits(world.checkout, "main")
    branch = "main"
    if change == "branch":
        branch = "other"
    elif change == "source":
        git(
            world.checkout,
            "remote",
            "set-url",
            "origin",
            "https://example.invalid/other.git",
        )
    elif change == "project":
        manifest_path = world.checkout / ".yoke/install-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["project_id"] = 8
        manifest_path.write_text(json.dumps(manifest))
    elif change == "identity":
        for row in writer.payload["created_commits"]:
            row["binding"]["git_inode"] += 1
        writer.write()
    else:
        writer.path.chmod(0o644)
    assert not receipts.verified_commits(world.checkout, branch)


def test_resume_retains_exact_receipts_and_step_detail(tmp_path, monkeypatch):
    _, writer, _, _ = setup_read_only(tmp_path, monkeypatch)
    preview = {
        "plan": {"steps": [{"action": "project-install-scaffold", "target": ""}]}
    }
    old = onboard_apply_report.ApplyReportWriter.start(preview, {})
    old.payload["created_commits"] = writer.payload["created_commits"]
    old.step_result("project-install-scaffold", "done", detail={"commit_sha": "proof"})
    resumed = onboard_apply_report.ApplyReportWriter.start(
        preview,
        {
            "resume_run_id": old.payload["run_id"],
            "resume_payload": old.payload,
        },
    )
    assert resumed.payload["created_commits"] == writer.payload["created_commits"]
    assert resumed.payload["steps"][0]["detail"] == {"commit_sha": "proof"}


def test_installer_proof_survives_later_install_failure(tmp_path, monkeypatch):
    from yoke_cli.commands.adapters import onboard_apply
    from yoke_cli.config.onboard_wizard import WizardApplyError

    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    from yoke_cli.project_install import harness_machine_persist

    monkeypatch.setattr(harness_machine_persist, "persist_install_glue", lambda *args: None)
    monkeypatch.setattr(runner, "sync_local_snapshot_for_write", lambda **kwargs: {})
    from runtime.api.cli.test_project_publication_settings import seed_project

    seed_project(world.checkout)
    destination.prevent_push(world.checkout)

    def fail_after_commit(**kwargs):
        raise RuntimeError("snapshot unavailable after installer commit")

    def build_report(**kwargs):
        if not kwargs.get("progress"):
            return {}
        runner.install(world.checkout, project_id=7)

    monkeypatch.setattr(runner, "sync_local_snapshot_for_write", fail_after_commit)
    monkeypatch.setattr(onboard_apply.onboard_config, "build_report", build_report)
    with pytest.raises(WizardApplyError, match="snapshot unavailable"):
        onboard_apply.apply_with_durable_report(
            {
                "project_checkout": str(world.checkout),
                "apply": True,
            },
            install_health=False,
        )
    sha = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    assert receipts.verified_commits(world.checkout, "main") == (sha,)


def test_active_setup_does_not_use_another_service_receipt(tmp_path, monkeypatch):
    world, _, _, _ = setup_read_only(tmp_path, monkeypatch)
    other = onboard_apply_report.ApplyReportWriter.start(
        {}, {"api_url": "https://other.invalid"}
    )
    with receipts.recording(other):
        assert receipts.verified_commits(world.checkout, "main") == ()


def test_refresh_migrates_legacy_local_remote_after_registration(tmp_path, monkeypatch):
    from yoke_cli.config import machine_config, writer_projects

    world, _, _, _ = setup_read_only(tmp_path, monkeypatch)
    writer_projects.set_publication_read_only(world.checkout, False)
    git(world.checkout, "config", "remote.origin.pushurl", destination.LEGACY_READ_ONLY_PUSH_URL)
    before = world.remote_tip()
    report = runner.install(world.checkout, project_id=7, operation="refresh")
    assert machine_config.project_entry(world.checkout)["publication_read_only"] is True
    assert destination.LEGACY_READ_ONLY_PUSH_URL not in destination.push_urls(world.checkout)
    assert git(world.checkout, "remote", "get-url", "origin").stdout.strip() == str(world.remote)
    assert report["publication"]["status"] == "publication_pending"
    assert world.remote_tip() == before
