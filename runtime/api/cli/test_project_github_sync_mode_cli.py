"""CLI coverage for explicit GitHub sync-mode repair."""

from __future__ import annotations

from yoke_cli.commands.adapters import project_github_sync_mode
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def test_repair_command_is_registered() -> None:
    function_id, adapter = SUBCOMMAND_REGISTRY[
        ("projects", "github-sync-mode", "repair")
    ]

    assert function_id == "projects.github_sync_mode.repair"
    assert adapter is project_github_sync_mode.projects_github_sync_mode_repair


def test_repair_adapter_is_dry_run_by_default(monkeypatch) -> None:
    captured = {}

    def dispatch_and_emit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        project_github_sync_mode,
        "dispatch_and_emit",
        dispatch_and_emit,
    )

    result = project_github_sync_mode.projects_github_sync_mode_repair(
        ["--project", "buzz"]
    )

    assert result == 0
    assert captured["function_id"] == "projects.github_sync_mode.repair"
    assert captured["target"].kind == "global"
    assert captured["payload"] == {"apply": False, "project": "buzz"}


def test_repair_adapter_requires_explicit_apply_flag(monkeypatch) -> None:
    captured = {}

    def dispatch_and_emit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        project_github_sync_mode,
        "dispatch_and_emit",
        dispatch_and_emit,
    )

    result = project_github_sync_mode.projects_github_sync_mode_repair(["--apply"])

    assert result == 0
    assert captured["payload"] == {"apply": True}
