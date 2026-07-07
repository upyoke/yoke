"""Tests for ``yoke project install``/``refresh`` file + manifest behavior.

Drives :func:`project_install.apply_bundle` (the network-free core) with a
fake bundle dict against a tmp repo; the seed-if-missing contract pass
lives in ``test_project_install_contract.py``; hook-merge specifics and
uninstall in ``test_project_install_hooks.py``.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import ProjectInstallError, apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_FILES,
    make_bundle,
)

MANIFEST_REL = ".yoke/install-manifest.json"


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def test_fresh_install_writes_files_manifest_and_hooks(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    for entry in DEFAULT_FILES:
        assert (repo / entry["path"]).read_text("utf-8") == entry["content"]
    assert sorted(report["files_written"]) == sorted(
        e["path"] for e in DEFAULT_FILES
    )
    manifest = _manifest(repo)
    assert manifest["manifest_schema"] == 1
    assert manifest["yoke_version"] == "9.9.9"
    assert manifest["project_id"] == 7
    assert set(manifest["files"]) == {e["path"] for e in DEFAULT_FILES}
    assert manifest["created_settings_files"] == [
        ".claude/settings.json", ".codex/hooks.json",
    ]
    assert (repo / ".claude/settings.json").is_file()
    assert (repo / ".codex/hooks.json").is_file()
    assert MANIFEST_REL not in manifest["files"]
    assert report["machine_config_newly_registered"] is False


def test_second_run_is_a_no_op(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    before = _manifest(repo)

    report = apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    assert report["files_written"] == []
    assert report["files_pruned"] == []
    assert report["hooks_added"] == {}
    assert report["warnings"] == []
    assert _manifest(repo) == before


def test_refresh_prunes_files_dropped_from_bundle(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    survivors = DEFAULT_FILES[:3]

    report = apply_bundle(
        repo, make_bundle(survivors), operation="refresh", source="test"
    )

    dropped = DEFAULT_FILES[3]["path"]
    assert report["files_pruned"] == [dropped]
    assert not (repo / dropped).exists()
    assert set(_manifest(repo)["files"]) == {e["path"] for e in survivors}


def test_refresh_preserves_locally_modified_dropped_file(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    dropped = DEFAULT_FILES[3]["path"]
    (repo / dropped).write_text("operator edits\n", encoding="utf-8")

    report = apply_bundle(
        repo, make_bundle(DEFAULT_FILES[:3]), operation="refresh", source="test"
    )

    assert report["files_pruned"] == []
    assert report["files_skipped_modified"] == [dropped]
    assert report["warnings"]
    assert (repo / dropped).read_text("utf-8") == "operator edits\n"
    assert dropped not in _manifest(repo)["files"]


def test_bundle_content_is_authority_over_local_edits(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    target = DEFAULT_FILES[0]["path"]
    (repo / target).write_text("local drift\n", encoding="utf-8")

    report = apply_bundle(repo, make_bundle(), operation="refresh", source="test")

    assert target in report["files_written"]
    assert (repo / target).read_text("utf-8") == DEFAULT_FILES[0]["content"]


@pytest.mark.parametrize("bad_path", [
    "../escape.md",
    "/etc/absolute.md",
    ".yoke/notes.md",
    ".claude/settings.json",
])
def test_unsafe_bundle_paths_are_refused(repo, bad_path) -> None:
    bundle = make_bundle([{"path": bad_path, "content": "x"}])

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, bundle, source="test")
    assert not (repo / MANIFEST_REL).exists()


def test_unsupported_bundle_schema_is_refused(repo) -> None:
    with pytest.raises(ProjectInstallError) as exc_info:
        apply_bundle(repo, make_bundle(bundle_schema=2), source="test")
    assert "rerun the public installer" in str(exc_info.value)


def test_unsupported_manifest_schema_is_refused(repo) -> None:
    (repo / ".yoke").mkdir()
    (repo / MANIFEST_REL).write_text(
        json.dumps({"manifest_schema": 99}), encoding="utf-8"
    )

    with pytest.raises(ProjectInstallError):
        apply_bundle(repo, make_bundle(), source="test")


def test_install_requires_a_resolvable_project_id(repo, tmp_path,
                                                  monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    cfg = tmp_path / "machine-home" / "config.json"

    with pytest.raises(ProjectInstallError) as exc_info:
        project_install.install(repo, config_path=cfg)
    assert "--project-id" in str(exc_info.value)


def test_install_registers_checkout_mapping_for_explicit_id(
    repo, tmp_path, monkeypatch
) -> None:
    from yoke_core.domain import machine_config, machine_config_writer

    cfg = tmp_path / "machine-home" / "config.json"
    dsn = tmp_path / "local.dsn"
    dsn.write_text("postgresql://localhost/yoke\n", encoding="utf-8")
    machine_config_writer.set_connection(
        "local", transport="local-postgres", dsn_file=str(dsn), path=cfg
    )
    monkeypatch.setattr(
        project_install, "_resolve_bundle",
        lambda pid, **kw: (make_bundle(), "test"),
    )

    report = project_install.install(repo, project_id=7, config_path=cfg)

    assert report["machine_config_newly_registered"] is True
    assert machine_config.project_id(repo, cfg) == 7

    # Second run: mapping exists, no re-registration; id resolves from config.
    report = project_install.refresh(repo, config_path=cfg)
    assert report["operation"] == "refresh"
    assert report["machine_config_newly_registered"] is False


def test_registration_failure_leaves_repo_untouched(
    repo, tmp_path, monkeypatch
) -> None:
    from yoke_core.domain.machine_config_writer import MachineConfigWriteError

    cfg = tmp_path / "machine-home" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}\n", encoding="utf-8")  # fails the writer contract
    monkeypatch.setattr(
        project_install, "_resolve_bundle",
        lambda pid, **kw: (make_bundle(), "test"),
    )

    with pytest.raises(MachineConfigWriteError):
        project_install.install(repo, project_id=7, config_path=cfg)

    assert not (repo / MANIFEST_REL).exists(), (
        "an unwritable machine config fails fast before any repo write"
    )
    assert not (repo / ".claude").exists()
    assert not (repo / ".yoke").exists()


def _git_init(root) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def test_manifest_and_report_record_copy_mode(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["mode"] == "copy"
    assert _manifest(repo)["mode"] == "copy"


def test_copy_install_writes_git_hook_shims(repo) -> None:
    from yoke_core.domain import project_install_git_hooks as git_hooks

    _git_init(repo)

    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["git_hooks_installed_or_updated"] == 2
    for name, marker in (
        ("pre-commit", git_hooks.PRE_COMMIT_MARKER),
        ("post-commit", git_hooks.POST_COMMIT_MARKER),
    ):
        hook = repo / ".git" / "hooks" / name
        assert hook.is_file(), f"{name} shim must be installed in copy mode"
        assert marker in hook.read_text(encoding="utf-8")

    rerun = apply_bundle(repo, make_bundle(), operation="refresh",
                         source="test")
    assert rerun["git_hooks_installed_or_updated"] == 0
    assert rerun["warnings"] == []


def test_copy_install_skips_git_hooks_without_git_dir(repo) -> None:
    report = apply_bundle(repo, make_bundle(), source="test")

    assert report["git_hooks_installed_or_updated"] == 0
    assert [a for a in report["git_hook_actions"] if "Skipped" in a]
    assert report["warnings"] == []


def test_copy_uninstall_removes_yoke_hooks_preserves_foreign(repo) -> None:
    _git_init(repo)
    apply_bundle(repo, make_bundle(), source="test")
    foreign = repo / ".git" / "hooks" / "post-commit"
    foreign.write_text("#!/bin/sh\nexec /custom/notify\n", encoding="utf-8")

    report = project_install.uninstall(repo)

    assert report["git_hooks_removed"] == ["pre-commit"]
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert foreign.read_text(encoding="utf-8") == (
        "#!/bin/sh\nexec /custom/notify\n"
    )


def test_install_refresh_drop_uninstall_round_trip(repo) -> None:
    apply_bundle(repo, make_bundle(), source="test")
    kept = DEFAULT_FILES[:2]
    dropped = [e["path"] for e in DEFAULT_FILES[2:]]

    report = apply_bundle(
        repo, make_bundle(files=kept), operation="refresh", source="test"
    )

    for path in dropped:
        assert path in report["files_pruned"]
        assert not (repo / path).exists()
    assert set(_manifest(repo)["files"]) == {e["path"] for e in kept}

    project_install.uninstall(repo)

    assert not (repo / MANIFEST_REL).exists()
    for entry in kept:
        assert not (repo / entry["path"]).exists()
