"""Tests for manifest-driven linked-lane hook enablement."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.agents_render_claude import render_claude_settings_json
from yoke_core.domain.agents_render_codex import render_codex_hooks_json
from yoke_core.domain.agents_render_cursor import render_cursor_hooks_json
from yoke_core.domain.worktree_harness_enablement import (
    load_hook_enablement_contributions,
    prepare_worktree_harnesses,
)


def test_all_harness_manifests_declare_lane_enablement() -> None:
    contributions = load_hook_enablement_contributions()
    by_harness = {item.harness_id: item for item in contributions}

    assert set(by_harness) == {"claude-code", "codex", "cursor"}
    assert by_harness["claude-code"].config_path == ".claude/settings.json"
    assert by_harness["cursor"].config_path == ".cursor/hooks.json"
    for contribution in contributions:
        assert contribution.root_env_var == "YOKE_ROOT"
        assert "verify_environment_export" in contribution.operations


def test_rendered_hook_commands_export_the_lane_root() -> None:
    for rendered in (
        render_claude_settings_json(),
        render_codex_hooks_json(),
        render_cursor_hooks_json(),
    ):
        assert "YOKE_ROOT=" in rendered


def test_lane_preparation_runs_declared_operations(tmp_path: Path, monkeypatch) -> None:
    adapter_root = tmp_path / "adapter"
    source = tmp_path / "checkout"
    target = source / ".worktrees" / "lane"
    for harness_id, config_path, operations in (
        (
            "claude-code",
            ".claude/settings.json",
            ["verify_hook_config", "verify_environment_export"],
        ),
        (
            "codex",
            ".codex/hooks.json",
            ["verify_hook_config", "verify_environment_export"],
        ),
        (
            "cursor",
            ".cursor/hooks.json",
            ["verify_hook_config", "verify_environment_export"],
        ),
    ):
        manifest_dir = adapter_root / "runtime" / "harness" / harness_id
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "harness_id": harness_id,
                    "supports": {"optional_local_affordances": ["session_start_hook"]},
                    "worktree_hook_enablement": {
                        "config_path": config_path,
                        "operations": operations,
                        "environment": {
                            "root_variable": "YOKE_ROOT",
                            "root_expression": "${PWD}",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        for root in (source, target):
            config_file = root / config_path
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(
                '{"hooks":{},"command":"env YOKE_ROOT=\\"${PWD}\\" yoke"}',
                encoding="utf-8",
            )

    reports = prepare_worktree_harnesses(
        str(source),
        str(target),
        adapter_root=str(adapter_root),
    )
    report_map = {report.harness_id: report for report in reports}

    assert set(report_map) == {"claude-code", "codex", "cursor"}
    assert report_map["claude-code"].actions == [
        "verified hook config",
        "verified YOKE_ROOT lane export",
    ]
    assert "verified YOKE_ROOT lane export" in report_map["codex"].actions
    assert report_map["cursor"].warnings == []
