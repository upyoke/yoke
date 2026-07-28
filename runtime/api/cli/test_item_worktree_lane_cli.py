"""CLI envelope coverage for item-owned worktree lanes."""

from __future__ import annotations

import subprocess
from io import StringIO
from types import SimpleNamespace

from yoke_cli import operation_inventory
from yoke_cli.commands.adapters import item_worktrees
from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def _capture_dispatch(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(item_worktrees, "dispatch_and_emit", _dispatch)
    return captured


def _clean_git_lane(tmp_path, *, worktree_id: int, branch: str) -> dict:
    path = tmp_path / branch
    path.mkdir()
    subprocess.run(
        ["git", "init", "-b", branch, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    (path / ".gitignore").write_text("cache/\n")
    (path / "evidence.txt").write_text("verified\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Yoke Test",
            "-c",
            "user.email=yoke-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Clean lane fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "id": worktree_id,
        "branch": branch,
        "path": str(path),
        "lane_role": "implementation",
        "state": "active",
    }


def _stub_lane_read(monkeypatch, lane: dict) -> None:
    monkeypatch.setattr(item_worktrees, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        item_worktrees,
        "build_actor",
        lambda **_kwargs: SimpleNamespace(session_id="test-session"),
    )
    monkeypatch.setattr(
        item_worktrees,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True,
            result={"worktree": lane},
        ),
    )


def test_get_builds_an_item_targeted_lane_read(monkeypatch) -> None:
    captured = _capture_dispatch(monkeypatch)

    assert (
        item_worktrees.item_worktrees_get(
            [
                "YOK-951",
                "--lane-role",
                "implementation",
                "--field",
                "branch",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "item_worktrees.get"
    assert captured["target"].kind == "item"
    assert captured["target"].item_ref == "YOK-951"
    assert captured["payload"] == {"lane_role": "implementation"}

    stdout = StringIO()
    captured["human_writer"](
        SimpleNamespace(
            success=True,
            result={"worktree": {"branch": "YOK-951"}},
        ),
        stdout,
        StringIO(),
    )
    assert stdout.getvalue() == "YOK-951\n"


def test_release_attests_a_clean_lane_before_dispatch(
    monkeypatch,
    tmp_path,
) -> None:
    captured = _capture_dispatch(monkeypatch)
    lane = _clean_git_lane(tmp_path, worktree_id=952, branch="YOK-952")
    _stub_lane_read(monkeypatch, lane)

    assert (
        item_worktrees.item_worktrees_release(
            [
                "YOK-952",
                "--all-active",
                "--reason",
                "evidence-only-recovery",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "item_worktrees.release"
    assert captured["target"].kind == "item"
    assert captured["target"].item_ref == "YOK-952"
    assert captured["payload"] == {
        "all_active": True,
        "reason": "evidence-only-recovery",
        "clean_lane_attestation": {
            "worktree_id": 952,
            "branch": "YOK-952",
            "path": lane["path"],
            "observed_clean": True,
        },
    }


def test_release_refuses_a_dirty_registered_lane(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    captured = _capture_dispatch(monkeypatch)
    lane = _clean_git_lane(tmp_path, worktree_id=953, branch="YOK-953")
    _stub_lane_read(monkeypatch, lane)
    (tmp_path / "YOK-953" / "uncommitted.txt").write_text("preserve me\n")

    assert (
        item_worktrees.item_worktrees_release(
            [
                "YOK-953",
                "--all-active",
                "--reason",
                "evidence-only-recovery",
            ]
        )
        == 1
    )

    assert captured == {}
    assert "worktree_cleanliness_unverified" in capsys.readouterr().err


def test_clean_lane_attestation_counts_ignored_files_as_dirty(tmp_path) -> None:
    lane = _clean_git_lane(tmp_path, worktree_id=954, branch="YOK-954")
    cache = tmp_path / "YOK-954" / "cache"
    cache.mkdir()
    (cache / "generated.txt").write_text("preserve me too\n")

    attestation, error = item_worktrees._attest_clean_lane(lane)

    assert attestation is None
    assert error is not None
    assert "not clean" in error


def test_list_and_path_record_build_registered_envelopes(monkeypatch) -> None:
    captured = _capture_dispatch(monkeypatch)

    assert item_worktrees.item_worktrees_list(["YOK-955"]) == 0
    assert captured["function_id"] == "item_worktrees.list"
    assert captured["payload"] == {}

    captured.clear()
    assert item_worktrees.item_worktrees_path_record([
        "YOK-955",
        "--worktree-id", "44",
        "--branch", "blitz/docs",
        "--path", "/tmp/blitz-docs",
    ]) == 0
    assert captured["function_id"] == "item_worktrees.path_record"
    assert captured["payload"] == {"path": "/tmp/blitz-docs"}
    assert captured["preconditions"] == {
        "worktree_id": 44,
        "branch": "blitz/docs",
    }


def test_registry_usage_and_inventory_expose_lane_operations() -> None:
    assert SUBCOMMAND_REGISTRY[("item-worktrees", "get")][0] == ("item_worktrees.get")
    assert SUBCOMMAND_REGISTRY[("item-worktrees", "list")][0] == (
        "item_worktrees.list"
    )
    assert SUBCOMMAND_REGISTRY[("item-worktrees", "path-record")][0] == (
        "item_worktrees.path_record"
    )
    assert SUBCOMMAND_REGISTRY[("item-worktrees", "release")][0] == (
        "item_worktrees.release"
    )
    assert ADAPTER_USAGE["item_worktrees.get"].startswith("yoke item-worktrees get")
    assert ADAPTER_USAGE["item_worktrees.list"].startswith("yoke item-worktrees list")
    assert ADAPTER_USAGE["item_worktrees.path_record"].startswith(
        "yoke item-worktrees path-record"
    )
    assert ADAPTER_USAGE["item_worktrees.release"].startswith(
        "yoke item-worktrees release"
    )
    assert operation_inventory.is_wrapped("yoke item-worktrees get")
    assert operation_inventory.is_wrapped("yoke item-worktrees list")
    assert operation_inventory.is_wrapped("yoke item-worktrees path-record")
    assert operation_inventory.is_wrapped("yoke item-worktrees release")
