"""Project-local install rendering for ExternalWebapp-style target repos."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.agents_render import detect_substrate_drift, write_all
from yoke_core.domain.agents_render_claude import render_claude_settings_json
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


def test_write_all_routes_project_install_targets(tmp_path: Path) -> None:
    target = tmp_path / "project"
    (target / ".agents").mkdir(parents=True)

    results = write_all(target_root=target, dry_run=False)

    assert ".claude/settings.json" in results
    assert ".codex/hooks.json" in results
    assert detect_substrate_drift(target_root=target) == []
