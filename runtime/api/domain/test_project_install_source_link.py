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
import subprocess
from pathlib import Path

import pytest

from yoke_cli.project_install import runner as project_install
from yoke_core.domain import project_install_source_link as source_link
from runtime.api.domain.native_view_test_support import seed_native_view_sources
from yoke_contracts.project_contract.source_native_views import NATIVE_AGENT_LINKS
from yoke_core.domain.agents_render_cursor import render_cursor_hooks_json
from yoke_cli.project_install.files import MANIFEST_REL, MODE_COPY, MODE_KEY, MODE_SOURCE_LINK
from yoke_contracts.project_contract.install_error import ProjectInstallError

MANIFEST_SCHEMA = 1


def _seed_yoke_checkout(root: Path) -> None:
    """Minimal tree satisfying ``is_yoke_source_checkout``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n', encoding="utf-8")
    (root / "runtime" / "harness").mkdir(parents=True)
    cursor_hooks = root / "runtime" / "harness" / "cursor" / "hooks.json"
    cursor_hooks.parent.mkdir(parents=True)
    cursor_hooks.write_text(render_cursor_hooks_json(), encoding="utf-8")
    claude_settings = root / "runtime" / "harness" / "claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True)
    claude_settings.write_text('{"hooks": {}}\n', encoding="utf-8")
    for harness in ("claude", "codex", "cursor"):
        manifest = root / "runtime" / "harness" / harness / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(f'{{"harness_id": "{harness}"}}\n', encoding="utf-8")
    seed_native_view_sources(root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


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
            MODE_COPY,
            "explicit --copy",
        )


class TestSourceLinkNativeViews:
    def test_creates_every_native_view(self, checkout):
        report = source_link.install_source_link(checkout)
        for native, source in NATIVE_AGENT_LINKS:
            assert (checkout / native).resolve() == (checkout / source).resolve()
            assert native.as_posix() in report["source_views_refreshed"]

    def test_stale_native_view_is_replaced(self, checkout):
        stale = checkout / ".claude" / "agents"
        stale.mkdir(parents=True)
        (stale / "old.md").write_text("stale\n", encoding="utf-8")
        report = source_link.install_source_link(checkout)
        assert ".claude/agents" in report["source_views_refreshed"]
        assert not (stale / "old.md").exists()
        assert (stale / "entry.md").read_text(encoding="utf-8") == "# rendered\n"


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
        assert "symlinks" not in manifest
        assert manifest["materialized_files"] == dict(
            source_link.DEV_MATERIALIZED_FILES
        )
        assert "git_hooks" not in manifest
        assert manifest["manifest_schema"] == MANIFEST_SCHEMA
        assert report[MODE_KEY] == MODE_SOURCE_LINK
        assert report["source"] == "in-checkout"

    def test_source_setup_retires_old_git_hooks(self, checkout):
        hooks = checkout / ".git/hooks"
        source_link.install_source_link(checkout, operation="dev.setup")
        assert all(hook.name.endswith(".sample") for hook in hooks.iterdir())
        old_hook = hooks / "pre-commit"
        old_hook.write_text(
            '#!/bin/sh\n# yoke-pre-commit hook installed by `yoke project install`\n'
            'exec yoke git pre-commit "$@"\n',
            encoding="utf-8",
        )
        report = source_link.install_source_link(checkout, operation="dev.setup")
        assert report["git_hooks_removed"] == ["pre-commit"]
        assert not old_hook.exists()

    def test_manifest_carries_unknown_keys_forward(self, checkout):
        (checkout / ".yoke").mkdir()
        (checkout / MANIFEST_REL).write_text(
            json.dumps({"manifest_schema": MANIFEST_SCHEMA, "future_key": "kept"}),
            encoding="utf-8",
        )
        source_link.install_source_link(checkout)
        assert _manifest(checkout)["future_key"] == "kept"


class TestInstallDispatch:
    def test_install_refuses_source_checkout_without_env(
        self, checkout, capsys
    ) -> None:
        _git_init(checkout)
        with pytest.raises(ProjectInstallError) as exc_info:
            project_install.install(checkout)
        assert "yoke dev setup" in str(exc_info.value)
        err = capsys.readouterr().err
        assert err == ""

    def test_install_announces_copy_strategy(
        self, plain_repo, monkeypatch, capsys
    ) -> None:
        _git_init(plain_repo)
        from yoke_core.domain.project_install_test_helpers import make_bundle

        monkeypatch.setattr(
            project_install,
            "_resolve_bundle",
            lambda pid, **kw: (make_bundle(), "test"),
        )
        monkeypatch.setattr(
            project_install,
            "_register_in_machine_config",
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
        assert "git-tracked source-dev files" in message
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
