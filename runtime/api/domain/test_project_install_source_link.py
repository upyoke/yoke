"""Tests for the source-link strategy + project-install handoff.

Exercises detection, the project-install handoff refusal, symlink repair,
git hook install, contract seeding, manifest
mode recording, and the source-link uninstall refusal — against scratch
directory trees and scratch git repos only, never the operator's real
checkout or its shared ``.git/``. Post-commit shim shape coverage lives
in ``runtime/api/test_post_commit_hook.py``; copy-mode file/manifest
behavior in ``test_project_install.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import project_install
from yoke_core.domain import project_install_git_hooks as git_hooks
from yoke_core.domain import project_install_source_link as source_link
from yoke_core.domain.project_install_files import (
    MANIFEST_REL,
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)

MANIFEST_SCHEMA = 1


def _seed_yoke_checkout(root: Path) -> None:
    """Minimal tree satisfying ``is_yoke_source_checkout``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8"
    )
    (root / "runtime" / "harness").mkdir(parents=True)


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _manifest(root: Path) -> dict:
    return json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "yoke-src"
    _seed_yoke_checkout(root)
    return root


@pytest.fixture
def plain_repo(tmp_path: Path) -> Path:
    root = tmp_path / "plain"
    root.mkdir()
    return root


class TestModeResolution:
    def test_plain_directory_resolves_copy(self, plain_repo):
        mode, reason = source_link.resolve_mode(plain_repo, None)
        assert mode == MODE_COPY
        assert reason == "external project repo"

    def test_wrong_project_name_resolves_copy(self, tmp_path):
        root = tmp_path / "other"
        root.mkdir()
        (root / "pyproject.toml").write_text(
            '[project]\nname = "externalwebapp"\n', encoding="utf-8"
        )
        (root / "runtime" / "harness").mkdir(parents=True)
        assert source_link.resolve_mode(root, None)[0] == MODE_COPY

    def test_missing_runtime_harness_resolves_copy(self, tmp_path):
        root = tmp_path / "no-harness"
        root.mkdir()
        (root / "pyproject.toml").write_text(
            '[project]\nname = "yoke"\n', encoding="utf-8"
        )
        assert source_link.resolve_mode(root, None)[0] == MODE_COPY

    def test_source_checkout_hands_off_to_dev_setup(self, checkout):
        assert source_link.is_yoke_source_checkout(checkout) is True
        with pytest.raises(ProjectInstallError) as exc_info:
            source_link.resolve_mode(checkout, None)
        message = str(exc_info.value)
        assert "yoke dev setup" in message
        assert "source-link" in message

    def test_explicit_source_link_outside_refuses(self, plain_repo):
        with pytest.raises(ProjectInstallError) as exc_info:
            source_link.resolve_mode(plain_repo, MODE_SOURCE_LINK)
        assert "yoke dev setup" in str(exc_info.value)

    def test_explicit_copy_inside_source_checkout_refuses(self, checkout):
        with pytest.raises(ProjectInstallError) as exc_info:
            source_link.resolve_mode(checkout, MODE_COPY)
        message = str(exc_info.value)
        assert "yoke dev setup" in message
        assert "source-link" in message

    def test_explicit_modes_pass_when_matched(self, checkout, plain_repo):
        with pytest.raises(ProjectInstallError):
            source_link.resolve_mode(checkout, MODE_SOURCE_LINK)
        assert source_link.resolve_mode(plain_repo, MODE_COPY) == (
            MODE_COPY, "explicit --copy"
        )


class TestSourceLinkSymlinks:
    def test_creates_all_symlinks(self, checkout):
        report = source_link.install_source_link(checkout)
        for rel, link_target in source_link.DEV_SYMLINKS:
            path = checkout / rel
            assert path.is_symlink(), f"{rel} must be a symlink"
            assert os.readlink(path) == link_target
        assert report["symlinks_created"] == len(source_link.DEV_SYMLINKS)
        assert any("Created: .claude/agents" in a for a in report["actions"])

    def test_idempotent_rerun_creates_nothing(self, checkout):
        source_link.install_source_link(checkout)
        report = source_link.install_source_link(checkout, operation="refresh")
        assert report["operation"] == "refresh"
        assert report["symlinks_created"] == 0
        assert report["symlinks_ok"] == len(source_link.DEV_SYMLINKS)
        assert report["warnings"] == []

    def test_wrong_target_symlink_left_in_place(self, checkout):
        path = checkout / ".claude"
        path.mkdir()
        (path / "agents").symlink_to("../somewhere/else")
        report = source_link.install_source_link(checkout)
        assert any(
            ".claude/agents is a symlink to ../somewhere/else" in w
            for w in report["warnings"]
        )
        assert os.readlink(checkout / ".claude" / "agents") == "../somewhere/else"

    def test_regular_dir_collision_left_in_place(self, checkout):
        (checkout / ".claude" / "agents").mkdir(parents=True)
        report = source_link.install_source_link(checkout)
        assert any(
            ".claude/agents exists as a regular file/dir" in w
            for w in report["warnings"]
        )
        assert not (checkout / ".claude" / "agents").is_symlink()


class TestSourceLinkGitHooks:
    def test_skips_hooks_without_git_dir(self, checkout):
        report = source_link.install_source_link(checkout)
        skips = [a for a in report["actions"] if "Skipped: .git/hooks/" in a]
        assert len(skips) == 2
        assert any("linked worktree" in a for a in skips)
        assert report["hooks_installed_or_updated"] == 0

    def test_installs_both_hooks_in_git_repo(self, checkout):
        _git_init(checkout)
        report = source_link.install_source_link(checkout)
        assert report["hooks_installed_or_updated"] == 2
        for name, marker, shim in (
            ("pre-commit", git_hooks.PRE_COMMIT_MARKER,
             git_hooks.PRE_COMMIT_SHIM),
            ("post-commit", git_hooks.POST_COMMIT_MARKER,
             git_hooks.POST_COMMIT_SHIM),
        ):
            hook = checkout / ".git" / "hooks" / name
            assert hook.is_file(), f"{name} hook must exist"
            assert os.access(hook, os.X_OK), f"{name} hook must be executable"
            text = hook.read_text(encoding="utf-8")
            assert marker in text
            assert text == shim

    def test_pre_commit_execs_installed_launcher(self):
        # One uniform shim text serves both delivery strategies: the dev
        # checkout's `yoke` is the editable install of the same code,
        # so source-link mode routes through the launcher too — the
        # module-invocation form is gone.
        assert "exec yoke git pre-commit" in git_hooks.PRE_COMMIT_SHIM
        assert (
            "python3 -m yoke_core.domain.git_pre_commit"
            not in git_hooks.PRE_COMMIT_SHIM
        )

    def test_preserves_foreign_pre_commit_hook(self, checkout):
        _git_init(checkout)
        hook = checkout / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexec /custom/check\n", encoding="utf-8")
        os.chmod(hook, 0o755)
        report = source_link.install_source_link(checkout)
        assert any("not Yoke-managed" in w for w in report["warnings"])
        assert "/custom/check" in hook.read_text(encoding="utf-8")

    def test_preserves_ambiguous_yoke_marker_hook(self, checkout):
        _git_init(checkout)
        hook = checkout / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            f"#!/bin/sh\n# {git_hooks.PRE_COMMIT_MARKER}\necho old\n",
            encoding="utf-8",
        )
        os.chmod(hook, 0o755)
        result = git_hooks.BootstrapResult()
        git_hooks.install_pre_commit_hook(checkout, result)
        assert result.updated == 0
        assert any("not Yoke-managed" in w for w in result.warnings)
        assert "echo old" in hook.read_text(encoding="utf-8")


class TestSourceLinkContractAndManifest:
    def test_seeds_contract_files_then_no_ops(self, checkout):
        report = source_link.install_source_link(checkout)
        assert report["contract_files_written"], "bare checkout gets seeded"
        assert (checkout / ".yoke" / "lint-config").is_file()

        rerun = source_link.install_source_link(checkout)
        assert rerun["contract_files_written"] == []
        assert sorted(rerun["contract_files_existing"]) == sorted(
            report["contract_files_written"]
        )

    def test_manifest_records_mode_and_link_inventory(self, checkout):
        report = source_link.install_source_link(checkout)
        manifest = _manifest(checkout)
        assert manifest[MODE_KEY] == MODE_SOURCE_LINK
        assert manifest["symlinks"] == dict(source_link.DEV_SYMLINKS)
        assert manifest["git_hooks"] == [
            "pre-commit",
            "post-commit",
            "pre-merge-commit",
        ]
        assert manifest["manifest_schema"] == MANIFEST_SCHEMA
        assert report[MODE_KEY] == MODE_SOURCE_LINK
        assert report["source"] == "in-checkout"

    def test_manifest_carries_unknown_keys_forward(self, checkout):
        (checkout / ".yoke").mkdir()
        (checkout / MANIFEST_REL).write_text(
            json.dumps({"manifest_schema": MANIFEST_SCHEMA,
                        "future_key": "kept"}),
            encoding="utf-8",
        )
        source_link.install_source_link(checkout)
        assert _manifest(checkout)["future_key"] == "kept"


class TestInstallDispatch:
    def test_install_refuses_source_checkout_without_env(
        self, checkout, capsys
    ) -> None:
        with pytest.raises(ProjectInstallError) as exc_info:
            project_install.install(checkout)
        assert "yoke dev setup" in str(exc_info.value)
        err = capsys.readouterr().err
        assert err == ""

    def test_install_announces_copy_strategy(
        self, plain_repo, monkeypatch, capsys
    ) -> None:
        from yoke_core.domain.project_install_test_helpers import make_bundle

        monkeypatch.setattr(
            project_install, "_resolve_bundle",
            lambda pid, **kw: (make_bundle(), "test"),
        )
        monkeypatch.setattr(
            project_install, "_register_in_machine_config",
            lambda *a, **kw: False,
        )
        report = project_install.install(plain_repo, project_id=7)
        assert report[MODE_KEY] == MODE_COPY
        assert "delivery strategy = copy" in capsys.readouterr().err

    def test_explicit_copy_refusal_via_install(self, checkout):
        with pytest.raises(ProjectInstallError):
            project_install.install(checkout, mode=MODE_COPY)
        assert not (checkout / MANIFEST_REL).exists()


class TestUninstallRefusal:
    def test_uninstall_refuses_on_source_link_manifest(self, checkout):
        source_link.install_source_link(checkout)
        with pytest.raises(ProjectInstallError) as exc_info:
            project_install.uninstall(checkout)
        message = str(exc_info.value)
        assert "refusing to uninstall" in message
        assert "git-tracked symlinks" in message
        assert (checkout / MANIFEST_REL).exists(), "manifest untouched"

    def test_uninstall_refuses_in_source_checkout_with_modeless_manifest(
        self, checkout
    ) -> None:
        # Detection backstop: a hand-edited or legacy manifest can never
        # authorize de-installing the source checkout.
        (checkout / ".yoke").mkdir()
        (checkout / MANIFEST_REL).write_text(
            json.dumps({"manifest_schema": MANIFEST_SCHEMA, "files": {}}),
            encoding="utf-8",
        )
        with pytest.raises(ProjectInstallError) as exc_info:
            project_install.uninstall(checkout)
        assert "refusing to uninstall" in str(exc_info.value)

    def test_modeless_manifest_in_plain_repo_uninstalls_as_copy(
        self, plain_repo
    ) -> None:
        # Reading existing pre-mode state: tolerated as a copy manifest.
        (plain_repo / ".yoke").mkdir()
        (plain_repo / MANIFEST_REL).write_text(
            json.dumps({"manifest_schema": MANIFEST_SCHEMA, "files": {}}),
            encoding="utf-8",
        )
        report = project_install.uninstall(plain_repo)
        assert report["operation"] == "uninstall"
        assert report[MODE_KEY] == MODE_COPY
        assert not (plain_repo / MANIFEST_REL).exists()
