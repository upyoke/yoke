"""Tests for Cursor hook surfacing and materialized-config drift checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_cursor_hooks as mod


def _seed(root: Path) -> bytes:
    payload = {
        "version": 1,
        "hooks": {"sessionStart": [{"command": "yoke hook evaluate SessionStart"}]},
    }
    content = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    canonical = root / "runtime" / "harness" / "cursor" / "hooks.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(content)
    claude_content = b'{"hooks": {}}\n'
    claude_canonical = root / "runtime/harness/claude/settings.json"
    claude_canonical.parent.mkdir(parents=True)
    claude_canonical.write_bytes(claude_content)
    agents = root / "runtime" / "harness" / "cursor" / "agents"
    agents.mkdir()
    native = root / ".cursor"
    native.mkdir()
    (native / "agents").symlink_to("../runtime/harness/cursor/agents")
    claude_project = root / ".claude/settings.json"
    claude_project.parent.mkdir(parents=True)
    claude_project.write_bytes(claude_content)
    return content


def _run(fn, root: Path, monkeypatch):
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(root))
    records = RecordCollector()
    fn(None, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_declares_cursor_checks() -> None:
    assert [check.slug for check in mod.PROJECT_HEALTH_CHECKS] == [
        "cursor-hook-events",
        "cursor-hook-surfacing",
        "cursor-hook-config-drift",
    ]


def test_materialized_cursor_config_passes(monkeypatch, tmp_path: Path) -> None:
    content = _seed(tmp_path)
    (tmp_path / ".cursor" / "hooks.json").write_bytes(content)

    surfacing = _run(mod.hc_cursor_hook_surfacing, tmp_path, monkeypatch)
    drift = _run(mod.hc_cursor_hook_config_drift, tmp_path, monkeypatch)

    assert surfacing.result == "PASS"
    assert drift.result == "PASS"


def test_symlinked_cursor_config_is_reported_as_unloadable(
    monkeypatch, tmp_path: Path,
) -> None:
    _seed(tmp_path)
    (tmp_path / ".cursor" / "hooks.json").symlink_to(
        "../runtime/harness/cursor/hooks.json"
    )

    surfacing = _run(mod.hc_cursor_hook_surfacing, tmp_path, monkeypatch)
    drift = _run(mod.hc_cursor_hook_config_drift, tmp_path, monkeypatch)

    assert surfacing.result == "FAIL"
    assert "refuses project hook config" in surfacing.detail
    assert drift.result == "FAIL"
    assert "Cursor may reject this project config" in drift.detail
    assert mod.cursor_hook_config_diagnostics(tmp_path)


def test_materialized_cursor_config_drift_is_reported(
    monkeypatch, tmp_path: Path,
) -> None:
    _seed(tmp_path)
    (tmp_path / ".cursor" / "hooks.json").write_text(
        '{"version": 1, "hooks": {}}\n', encoding="utf-8"
    )

    result = _run(mod.hc_cursor_hook_config_drift, tmp_path, monkeypatch)

    assert result.result == "FAIL"
    assert "differs from canonical" in result.detail


def test_symlinked_claude_config_is_reported_as_unloadable(
    monkeypatch, tmp_path: Path,
) -> None:
    content = _seed(tmp_path)
    (tmp_path / ".cursor/hooks.json").write_bytes(content)
    settings = tmp_path / ".claude/settings.json"
    settings.unlink()
    settings.symlink_to("../runtime/harness/claude/settings.json")

    surfacing = _run(mod.hc_cursor_hook_surfacing, tmp_path, monkeypatch)
    drift = _run(mod.hc_cursor_hook_config_drift, tmp_path, monkeypatch)

    assert surfacing.result == "FAIL"
    assert ".claude/settings.json contains symlink component" in surfacing.detail
    assert drift.result == "FAIL"
    assert "Cursor may reject this project config" in drift.detail


@pytest.mark.parametrize(
    ("parent_rel", "project_rel"),
    [
        (".claude", ".claude/settings.json"),
        (".cursor", ".cursor/hooks.json"),
    ],
)
def test_symlinked_config_parent_is_reported_as_unloadable(
    monkeypatch,
    tmp_path: Path,
    parent_rel: str,
    project_rel: str,
) -> None:
    content = _seed(tmp_path)
    (tmp_path / ".cursor/hooks.json").write_bytes(content)
    parent = tmp_path / parent_rel
    real_parent = tmp_path / f"{parent_rel}-real"
    parent.rename(real_parent)
    parent.symlink_to(real_parent.name, target_is_directory=True)

    surfacing = _run(mod.hc_cursor_hook_surfacing, tmp_path, monkeypatch)
    drift = _run(mod.hc_cursor_hook_config_drift, tmp_path, monkeypatch)

    assert surfacing.result == "FAIL"
    assert f"{project_rel} contains symlink component {parent_rel}" in (
        surfacing.detail
    )
    assert drift.result == "FAIL"
    assert f"{project_rel} contains symlink component {parent_rel}" in drift.detail
