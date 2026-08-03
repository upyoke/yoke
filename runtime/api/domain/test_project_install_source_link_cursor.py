"""Cursor-specific source-link materialization coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_install_source_link as source_link
from yoke_core.domain.agents_render_cursor import render_cursor_hooks_json


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "yoke-src"
    (root / "runtime" / "harness" / "cursor").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n', encoding="utf-8",
    )
    (root / "runtime" / "harness" / "cursor" / "hooks.json").write_text(
        render_cursor_hooks_json(), encoding="utf-8",
    )
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
