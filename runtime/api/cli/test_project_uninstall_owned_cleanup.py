"""Project retirement uses disposable checkouts, machine config and harness state."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from yoke_contracts import harness_folder_trust as trust
from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.codex_config_posture import parse_config
from yoke_contracts.harness_folder_trust_grant import grant_folder_trust
from yoke_cli.config import machine_config, writer
from yoke_cli.project_install import files, owned_cleanup, uninstall_commit
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.uninstall import uninstall
from yoke_core.domain.project_install_test_helpers import make_bundle


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def installed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    launcher = home / "bin/yoke"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(launcher.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    config = tmp_path / "machine/config.json"
    writer.set_connection(
        "local",
        transport="https",
        api_url="https://fixture.invalid",
        token="fixture-only",
        path=config,
    )
    roots = [tmp_path / "selected", tmp_path / "other"]
    trust.claude_state_path().write_text('{"projects": {}, "signIn": "keep"}')
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text('# personal\nmodel = "keep"\n')
    trust.cursor_projects_root().mkdir(parents=True)
    for index, root in enumerate(roots, 7):
        root.mkdir()
        git(root, "init", "-b", "main")
        # Keep asynchronous Git maintenance out of exact preservation snapshots.
        git(root, "config", "maintenance.auto", "false")
        git(root, "config", "gc.auto", "0")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.com")
        bundle = make_bundle()
        bundle["project_id"] = index
        apply_bundle(root, bundle, source="fixture")
        writer.register_project(root, index, path=config)
        owned_cleanup.record_registration(root, index, config)
        grant_folder_trust(root)
        git(root, "add", "-A")
        git(root, "commit", "--no-verify", "-m", "Fixture install")
    return roots[0], roots[1], config


def read_json(path):
    return json.loads(path.read_text())


def test_uninstall_only_exact_owned_entries_and_preserves_shared_state(installed):
    root, other, config = installed
    other_files = {p: p.read_bytes() for p in other.rglob("*") if p.is_file()}
    config_before = read_json(config)
    other_cursor = trust.cursor_trust_file(other).read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "complete", report
    assert report["manifest_removed"]
    assert read_json(config) == {
        **config_before,
        "projects": [{"checkout": str(other), "project_id": 8}],
    }
    assert read_json(trust.claude_state_path()) == {
        "projects": {str(other): {"hasTrustDialogAccepted": True}},
        "signIn": "keep",
    }
    codex = parse_config((Path.home() / ".codex/config.toml").read_text())
    assert str(root) not in codex["projects"] and str(other) in codex["projects"]
    assert codex["model"] == "keep" and codex["approval_policy"] == "never"
    assert not trust.cursor_trust_file(root).exists()
    assert trust.cursor_trust_file(other).read_bytes() == other_cursor
    assert {p: p.read_bytes() for p in other_files} == other_files
    assert all(entry.get("trust_key") != str(root) for entry in ledger.read())
    assert not git(root, "status", "--porcelain")
    with pytest.raises(files.ProjectInstallError, match="no install manifest"):
        uninstall(root, config_path=config)


@pytest.mark.parametrize("family", ["claude-code", "codex", "cursor"])
def test_changed_trust_is_preserved_and_retry_is_honest(installed, family):
    root, _, config = installed
    if family == "claude-code":
        target = trust.claude_state_path()
        payload = read_json(target)
        payload["projects"][str(root)]["hasTrustDialogAccepted"] = False
        target.write_text(json.dumps(payload))
    elif family == "codex":
        target = Path.home() / ".codex/config.toml"
        target.write_text(
            target.read_text().replace(
                'trust_level = "trusted"', 'trust_level = "untrusted"'
            )
        )
    else:
        target = trust.cursor_trust_file(root)
        payload = read_json(target)
        payload["trustedAt"] = "operator-replaced"
        target.write_text(json.dumps(payload))
    before = target.read_bytes()
    for _ in range(2):
        report = uninstall(root, config_path=config)
        assert report["outcome"] == "partial"
        assert not report["manifest_removed"]
        assert target.read_bytes() == before
        assert any(
            row["harness"] == family and row["status"] == "preserved"
            for row in report["local_cleanup"]["trust"]
        )
    assert machine_config.project_id(root, config) == 7


@pytest.mark.parametrize("evidence", ["missing", "edited", "other_config"])
def test_unproven_registration_stays(installed, evidence):
    root, _, config = installed
    manifest = files.load_manifest(root)
    if evidence == "missing":
        del manifest[owned_cleanup.REGISTRATION_KEY]
    elif evidence == "edited":
        payload = read_json(config)
        payload["projects"][0]["checkout"] += " "
        config.write_text(json.dumps(payload))
    else:
        manifest[owned_cleanup.REGISTRATION_KEY]["config"] += ".other"
    files.write_manifest(root, manifest)
    git(root, "add", "-A")
    if git(root, "status", "--porcelain"):
        git(root, "commit", "--no-verify", "-m", "Change fixture evidence")
    before = config.read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert config.read_bytes() == before
    assert report["local_cleanup"]["registration"]["status"] == "preserved"


@pytest.mark.parametrize("sharing", ["nested", "worktree", "broader", "trust_slug"])
def test_shared_checkout_scope_is_preserved(installed, sharing):
    root, other, config = installed
    if sharing == "nested":
        nested = root / "nested"
        nested.mkdir()
        writer.register_project(nested, 9, path=config)
    elif sharing == "worktree":
        git(root, "worktree", "add", "-b", "feature", str(root.parent / "lane"))
    elif sharing == "broader":
        writer.register_project(root.parent, 9, path=config)
    else:
        collision = root.parent / "select.ed"
        collision.mkdir()
        writer.register_project(collision, 9, path=config)
        assert trust.cursor_trust_file(collision) == trust.cursor_trust_file(root)
    hooks = {p: p.read_bytes() for p in (root / ".git/hooks").iterdir() if p.is_file()}
    ignore_before = (root / ".gitignore").read_bytes()
    before = config.read_bytes(), trust.claude_state_path().read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert (config.read_bytes(), trust.claude_state_path().read_bytes()) == before
    assert machine_config.project_id(other, config) == 8
    assert {p: p.read_bytes() for p in hooks} == hooks
    assert report["git_hooks_preserved_reason"]
    assert (root / ".gitignore").read_bytes() == ignore_before


def test_unknown_and_legacy_trust_is_preserved(installed):
    root, _, config = installed
    with ledger.mutation() as entries:
        for entry in list(entries):
            if entry.get("kind") == "json" and str(root) in entry.get("keys", []):
                entries.remove(entry)
            elif entry.get("kind") == "created_file":
                entry.pop("sha256", None)
    before = trust.cursor_trust_file(root).read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    reasons = {row["reason"] for row in report["local_cleanup"]["trust"]}
    assert {"trust_ownership_unknown", "trust_modified_or_unproven"} <= reasons
    assert trust.cursor_trust_file(root).read_bytes() == before


def test_broader_trust_is_not_removed(installed):
    from yoke_contracts.harness_folder_trust_revert import revert_folder_trust

    root, _, config = installed
    grant_folder_trust(root.parent)
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert any(
        row["reason"] == "broader_trust" for row in report["local_cleanup"]["trust"]
    )
    assert str(root.parent) in read_json(trust.claude_state_path())["projects"]
    revert_folder_trust(root.parent)
    assert uninstall(root, config_path=config)["outcome"] == "complete"


def test_cleanup_failure_keeps_manifest_for_retry(installed, monkeypatch):
    root, _, config = installed
    monkeypatch.setattr(
        owned_cleanup,
        "_shared_reason",
        lambda *a: (_ for _ in ()).throw(OSError("fixture unavailable")),
    )
    before = config.read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert files.load_manifest(root)
    assert config.read_bytes() == before
    assert "project_uninstall_local_cleanup_unavailable" in " ".join(report["warnings"])


def test_partial_cleanup_returns_nonzero_from_existing_command(installed, capsys):
    from yoke_cli.commands.adapters.install import project_uninstall

    root, _, config = installed
    with ledger.mutation() as entries:
        entries.clear()
    assert project_uninstall([str(root), "--config", str(config), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "partial"


def test_later_harness_home_keeps_unowned_trust(installed, monkeypatch):
    root, _, config = installed
    later = Path.home() / "later-codex"
    later.mkdir()
    target = later / "config.toml"
    content = f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n'
    target.write_text(content)
    monkeypatch.setenv("CODEX_HOME", str(later))
    report = uninstall(root, config_path=config)
    assert target.read_text() == content
    assert report["outcome"] == "partial"
    assert any(
        row["harness"] == "codex" and row["reason"] == "trust_ownership_unknown"
        for row in report["local_cleanup"]["trust"]
    )


def test_unowned_symlink_alias_trust_is_preserved_and_reported(installed):
    root, _, config = installed
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    target = Path.home() / ".codex/config.toml"
    target.write_text(
        target.read_text()
        + f'\n[projects.{json.dumps(str(alias))}]\ntrust_level = "trusted"\n'
    )
    report = uninstall(root, config_path=config)
    assert str(alias) in parse_config(target.read_text())["projects"]
    assert report["outcome"] == "partial"
    assert any(
        row["reason"] == "trust_ownership_unknown"
        for row in report["local_cleanup"]["trust"]
    )


def test_reassigned_checkout_preserves_trust_for_its_current_project(installed):
    root, _, config = installed
    writer.register_project(root, 99, reassign=True, path=config)
    before = trust.claude_state_path().read_bytes()
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert machine_config.project_id(root, config) == 99
    assert trust.claude_state_path().read_bytes() == before
    assert (
        report["local_cleanup"]["registration"]["reason"]
        == "registration_project_identity_changed"
    )


def test_registration_write_failure_retains_truthful_trust_results(
    installed, monkeypatch
):
    root, _, config = installed
    from yoke_cli.config import machine_config_file

    before = config.read_bytes()
    with monkeypatch.context() as patch:

        def fail(*args):
            raise OSError("fixture write unavailable")

        patch.setattr(machine_config_file, "atomic_write_text", fail)
        report = uninstall(root, config_path=config)
    assert report["outcome"] == "partial"
    assert report["local_cleanup"]["registration"]["status"] == "failed"
    assert {row["status"] for row in report["local_cleanup"]["trust"]} == {"removed"}
    assert config.read_bytes() == before
    assert files.load_manifest(root)
    assert uninstall(root, config_path=config)["outcome"] == "complete"


def test_commit_failure_keeps_local_ownership_for_recovery(installed, monkeypatch):
    root, _, config = installed
    before = config.read_bytes(), trust.claude_state_path().read_bytes()

    def fail(*args):
        raise files.ProjectInstallError("project_uninstall_commit_failed: fixture")

    monkeypatch.setattr(uninstall_commit, "commit", fail)
    with pytest.raises(
        files.ProjectInstallError, match="project_uninstall_commit_failed"
    ):
        uninstall(root, config_path=config)
    assert files.load_manifest(root)
    assert (config.read_bytes(), trust.claude_state_path().read_bytes()) == before


def test_different_empty_config_does_not_hide_the_recorded_registration(installed):
    root, _, config = installed
    other_config = config.with_name("other.json")
    payload = read_json(config)
    payload["projects"] = []
    other_config.write_text(json.dumps(payload))
    before = config.read_bytes(), trust.claude_state_path().read_bytes()
    report = uninstall(root, config_path=other_config)
    assert report["outcome"] == "partial"
    assert (
        report["local_cleanup"]["registration"]["reason"]
        == "registration_config_changed"
    )
    assert files.load_manifest(root)
    assert (config.read_bytes(), trust.claude_state_path().read_bytes()) == before
