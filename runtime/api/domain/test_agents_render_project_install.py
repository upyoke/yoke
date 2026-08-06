"""Project-local install rendering for ExternalWebapp-style target repos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.agents_render import detect_substrate_drift, write_all
from yoke_core.domain.agents_render_claude import render_claude_settings_json
from yoke_core.domain.agents_render_cursor import render_cursor_hooks_json
from yoke_core.domain.agents_render_project_install import (
    detect_project_install_drift,
    write_project_install,
)


def test_project_install_render_and_drift_check(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    write_project_install(target_root=target)

    assert detect_project_install_drift(target_root=target) == []
    assert detect_substrate_drift(target_root=target) == []
    assert (target / ".claude" / "settings.json").read_text() == (
        render_claude_settings_json()
    )
    assert "YOKE_EXECUTOR=claude" not in (
        target / ".claude" / "settings.json"
    ).read_text()


def test_project_install_dereferences_claude_reference_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "project"
    target.mkdir()

    write_project_install(target_root=target)

    reference = (
        target / ".claude" / "agents" / "references" / "yoke-tester-browser.md"
    )
    assert reference.is_file()
    assert not reference.is_symlink()
    assert "Tester Browser Scenario Execution" in reference.read_text()


def test_external_install_materializes_cursor_hooks_file(tmp_path: Path) -> None:
    target = tmp_path / "external"
    target.mkdir()

    write_project_install(target_root=target)

    hooks = target / ".cursor" / "hooks.json"
    assert hooks.is_file()
    assert not hooks.is_symlink()
    assert hooks.read_text(encoding="utf-8") == render_cursor_hooks_json()
    assert detect_project_install_drift(target_root=target) == []


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        (Path(".claude/settings.json"), render_claude_settings_json()),
        (Path(".cursor/hooks.json"), render_cursor_hooks_json()),
    ],
)
def test_project_install_render_materializes_byte_equal_config_symlink(
    tmp_path: Path, relative: Path, content: str,
) -> None:
    target = tmp_path / "project"
    canonical = target / "canonical" / relative.name
    canonical.parent.mkdir(parents=True)
    canonical.write_text(content, encoding="utf-8")
    scanned = target / relative
    scanned.parent.mkdir(parents=True)
    scanned.symlink_to(canonical)

    results = write_project_install(target_root=target)

    assert results[str(relative)][0] == "write"
    assert scanned.is_file() and not scanned.is_symlink()
    assert scanned.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("parent_rel", [".claude", ".cursor"])
def test_project_install_render_refuses_symlinked_config_parent(
    tmp_path: Path, parent_rel: str,
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    real_parent = target / f"{parent_rel}-real"
    real_parent.mkdir()
    (target / parent_rel).symlink_to(
        real_parent.name, target_is_directory=True,
    )

    with pytest.raises(RuntimeError, match="symlinked parent"):
        write_project_install(target_root=target)

    assert list(real_parent.iterdir()) == []


def test_write_all_routes_project_install_targets(tmp_path: Path) -> None:
    target = tmp_path / "project"
    (target / ".agents").mkdir(parents=True)

    results = write_all(target_root=target, dry_run=False)

    assert ".claude/settings.json" in results
    assert ".codex/hooks.json" in results
    assert detect_substrate_drift(target_root=target) == []


def test_copy_install_manifest_keeps_skill_directories_as_copies(tmp_path: Path) -> None:
    target = tmp_path / "project"
    (target / ".agents").mkdir(parents=True)
    manifest = target / ".yoke" / "install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"mode": "copy"}), encoding="utf-8")

    write_project_install(target_root=target)

    claude_skill = target / ".claude" / "skills" / "yoke" / "SKILL.md"
    codex_skill = target / ".codex" / "skills" / "yoke" / "SKILL.md"
    canonical_skill = target / ".agents" / "skills" / "yoke" / "SKILL.md"
    assert claude_skill.is_file() and not claude_skill.is_symlink()
    assert codex_skill.is_file() and not codex_skill.is_symlink()
    assert claude_skill.read_text() == canonical_skill.read_text()
    assert codex_skill.read_text() == canonical_skill.read_text()
    assert detect_project_install_drift(target_root=target) == []
