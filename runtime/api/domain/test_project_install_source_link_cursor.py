"""Cursor-specific source-link materialization and permission coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_ALLOW,
    CURSOR_CLI_REL,
    CURSOR_SANDBOX_REL,
)
from yoke_core.domain import project_install_source_link as source_link
from yoke_core.domain.agents_render_cursor import render_cursor_hooks_json
from yoke_core.domain.project_install_files import ProjectInstallError

CONFIGURED_ORIGIN = "control.example.test"


@pytest.fixture
def machine_home(tmp_path: Path, monkeypatch) -> Path:
    """Isolated machine config declaring one https control plane."""
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    (home / "config.json").write_text(
        json.dumps(
            {
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": f"https://{CONFIGURED_ORIGIN}/api/orgs/acme",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return home


@pytest.fixture
def checkout(tmp_path: Path, machine_home: Path) -> Path:
    root = tmp_path / "yoke-src"
    (root / "runtime" / "harness" / "cursor").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8",
    )
    (root / "runtime" / "harness" / "cursor" / "hooks.json").write_text(
        render_cursor_hooks_json(), encoding="utf-8",
    )
    claude_settings = root / "runtime" / "harness" / "claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True)
    claude_settings.write_text('{"hooks": {}}\n', encoding="utf-8")
    return root


def test_source_link_materializes_cursor_hooks_file(checkout) -> None:
    report = source_link.install_source_link(checkout)

    cursor_hooks = checkout / ".cursor" / "hooks.json"
    assert cursor_hooks.is_file()
    assert not cursor_hooks.is_symlink()
    assert cursor_hooks.read_bytes() == (
        checkout / "runtime" / "harness" / "cursor" / "hooks.json"
    ).read_bytes()
    assert report["materialized_files_created"] == len(
        source_link.DEV_MATERIALIZED_FILES
    )

    for rel, source_rel in source_link.DEV_MATERIALIZED_FILES:
        target = checkout / rel
        assert target.is_file(), f"{rel} must be a regular file"
        assert not target.is_symlink()
        assert target.read_bytes() == (checkout / source_rel).read_bytes()


def test_source_link_materialized_cursor_config_is_idempotent(checkout) -> None:
    source_link.install_source_link(checkout)

    report = source_link.install_source_link(checkout, operation="refresh")

    assert report["operation"] == "refresh"
    assert report["materialized_files_created"] == 0
    assert report["materialized_files_updated"] == 0
    assert report["materialized_files_ok"] == len(
        source_link.DEV_MATERIALIZED_FILES
    )
    assert report["warnings"] == []


def test_source_link_applies_the_cursor_permission_regions(checkout) -> None:
    report = source_link.install_source_link(checkout)

    cli = json.loads((checkout / CURSOR_CLI_REL).read_text(encoding="utf-8"))
    assert cli["permissions"]["allow"] == list(CURSOR_CLI_ALLOW)
    sandbox = json.loads(
        (checkout / CURSOR_SANDBOX_REL).read_text(encoding="utf-8")
    )
    assert sandbox["networkPolicy"]["allow"] == [CONFIGURED_ORIGIN]
    assert any("Updated: " + CURSOR_CLI_REL in line for line in report["actions"])


def test_source_link_records_cursor_regions_in_the_manifest(checkout) -> None:
    source_link.install_source_link(checkout)

    manifest = json.loads(
        (checkout / ".yoke" / "install-manifest.json").read_text(encoding="utf-8")
    )
    records = manifest["cursor_permissions"]
    assert records[CURSOR_CLI_REL]["added_entries"] == list(CURSOR_CLI_ALLOW)
    assert records[CURSOR_SANDBOX_REL]["set_default"] is True


def test_source_link_migrates_legacy_cursor_hook_symlink(checkout) -> None:
    cursor_dir = checkout / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "hooks.json").symlink_to(
        "../runtime/harness/cursor/hooks.json"
    )

    report = source_link.install_source_link(checkout, operation="refresh")

    target = cursor_dir / "hooks.json"
    assert target.is_file()
    assert not target.is_symlink()
    assert report["materialized_files_updated"] == 1
    assert target.read_bytes() == (
        checkout / "runtime" / "harness" / "cursor" / "hooks.json"
    ).read_bytes()


def test_source_link_migrates_legacy_claude_settings_symlink(checkout) -> None:
    settings = checkout / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.symlink_to("../runtime/harness/claude/settings.json")

    report = source_link.install_source_link(checkout, operation="refresh")

    assert settings.is_file()
    assert not settings.is_symlink()
    assert settings.read_bytes() == (
        checkout / "runtime/harness/claude/settings.json"
    ).read_bytes()
    assert report["materialized_files_updated"] == 1


def test_source_link_does_not_follow_predictable_temp_symlink(checkout) -> None:
    victim = checkout.parent / "outside-settings.json"
    victim.write_text("operator data\n", encoding="utf-8")
    temporary = checkout / ".claude/settings.json.tmp"
    temporary.parent.mkdir(parents=True)
    temporary.symlink_to(victim)

    source_link.install_source_link(checkout)

    assert victim.read_text(encoding="utf-8") == "operator data\n"
    assert temporary.is_symlink()
    assert (checkout / ".claude/settings.json").read_bytes() == (
        checkout / "runtime/harness/claude/settings.json"
    ).read_bytes()


@pytest.mark.parametrize("parent_rel", [".claude", ".cursor"])
def test_source_link_refuses_internal_symlinked_config_parent(
    checkout: Path, parent_rel: str,
) -> None:
    real_parent = checkout / f"{parent_rel}-real"
    real_parent.mkdir()
    (checkout / parent_rel).symlink_to(
        real_parent.name, target_is_directory=True,
    )

    with pytest.raises(ProjectInstallError, match="symlinked parent"):
        source_link.install_source_link(checkout)

    assert list(real_parent.iterdir()) == []
    assert not (checkout / ".yoke/install-manifest.json").exists()
