"""Installer proposal creation has no agent-facing CLI adapter."""

import json
from pathlib import Path

from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.registry_github import GITHUB_SUBCOMMAND_REGISTRY
from yoke_cli.main import main as cli_main
from yoke_cli.operation_inventory_data import WRAPPED_ROWS

ROOT = Path(__file__).resolve().parents[3]


def test_pr_create_command_is_unknown(capsys):
    assert cli_main(["github", "pr", "create", "--help"]) != 0
    captured = capsys.readouterr()
    assert "unknown" in (captured.out + captured.err).lower()
    assert ("github", "pr", "create") not in GITHUB_SUBCOMMAND_REGISTRY
    assert "github.pr.create" not in ADAPTER_USAGE


def test_pr_create_is_absent_from_teaching_and_inventory():
    summaries = json.loads((ROOT / (
        "packages/yoke-cli/src/yoke_cli/commands/summaries/github.json"
    )).read_text())
    assert "github pr" not in summaries
    assert "github pr create" not in summaries
    assert "yoke github pr create" not in repr(WRAPPED_ROWS)
    landing = json.loads((ROOT / (
        "docs/teaching/model/concepts/merging/landing.json"
    )).read_text())
    assert "yoke github pr create" not in landing["commands"]
    assert "github.pr.create" not in landing["functions"]


def test_shipped_sources_do_not_teach_deleted_command():
    stale = []
    for directory in ("packages", "docs/teaching", ".yoke/docs"):
        for source in (ROOT / directory).rglob("*"):
            if not source.is_file() or source.suffix not in {".py", ".md", ".json"}:
                continue
            if {"archive", "views", "__pycache__"} & set(source.parts):
                continue
            if "yoke github pr create" in source.read_text():
                stale.append(str(source.relative_to(ROOT)))
    assert stale == []
