"""CLI envelope coverage for explicit additional item worktree lanes."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from yoke_cli import operation_inventory
from yoke_cli.commands.adapters import item_worktree_create
from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def test_create_builds_an_item_targeted_lane_registration(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(item_worktree_create, "dispatch_and_emit", _dispatch)

    assert (
        item_worktree_create.item_worktrees_create(
            [
                "YOK-971",
                "--lane-role",
                "worker",
                "--branch",
                "blitz/docs",
                "--project",
                "yoke",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "item_worktrees.create"
    assert captured["target"].kind == "item"
    assert captured["target"].public_ref == "YOK-971"
    assert captured["target"].project_id == "yoke"
    assert captured["payload"] == {
        "lane_role": "worker",
        "branch": "blitz/docs",
    }

    stdout = StringIO()
    captured["human_writer"](
        SimpleNamespace(
            result={
                "worktree": {
                    "id": 44,
                    "lane_role": "worker",
                    "branch": "blitz/docs",
                    "path": None,
                }
            }
        ),
        stdout,
        StringIO(),
    )
    assert stdout.getvalue() == "item-worktree-created|44|worker|blitz/docs|\n"


def test_create_rejects_the_default_implementation_role(capsys) -> None:
    result = item_worktree_create.item_worktrees_create(
        [
            "YOK-972",
            "--lane-role",
            "implementation",
            "--branch",
            "YOK-972",
        ]
    )

    assert result == 2
    assert "invalid choice" in capsys.readouterr().err


def test_create_without_lane_flags_ensures_the_default(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(item_worktree_create, "dispatch_and_emit", _dispatch)

    assert item_worktree_create.item_worktrees_create(["YOK-973"]) == 0
    assert captured["function_id"] == "item_worktrees.create"
    assert captured["payload"] == {}


def test_registry_usage_and_inventory_expose_creation() -> None:
    function_id, adapter = SUBCOMMAND_REGISTRY[("item-worktrees", "create")]
    assert function_id == "item_worktrees.create"
    assert adapter is item_worktree_create.item_worktrees_create
    assert ADAPTER_USAGE["item_worktrees.create"].startswith(
        "yoke item-worktrees create"
    )
    assert operation_inventory.is_wrapped("yoke item-worktrees create")
