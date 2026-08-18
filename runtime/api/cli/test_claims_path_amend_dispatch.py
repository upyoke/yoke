"""CLI contract for add-or-remove path-claim amendments."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

from yoke_cli.commands.adapters.claims_path_change import claims_path_amend
from yoke_cli.commands.adapters.claims_path_narrow_evidence import (
    collect_narrow_boundary_evidence,
)


_HEAD = "a" * 40
_EVIDENCE = {
    "repo_root": "/client/worktree",
    "head_sha": _HEAD,
    "integration_target": "main",
    "touched_paths": ["src/keep.py"],
    "uncommitted_paths": [],
    "rename_pairs": [],
}


def test_remove_paths_dispatches_synced_boundary_evidence():
    with (
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "collect_narrow_boundary_evidence",
            return_value=_EVIDENCE,
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "sync_local_snapshot_for_write",
            return_value={"status": "ok", "message": ""},
        ) as sync,
        patch(
            "yoke_cli.commands.adapters.claims_path_change.dispatch_and_emit",
            return_value=0,
        ) as dispatch,
    ):
        result = claims_path_amend(
            [
                "--claim-id",
                "41",
                "--remove-paths",
                "src/unused.py",
                "--integration-target",
                "main",
                "--reason",
                "remove unused path",
                "--item",
                "YOK-9405",
            ]
        )

    assert result == 0
    sync.assert_called_once_with(
        project=None,
        repo_root="/client/worktree",
        integration_target="main",
        session_id=None,
    )
    call = dispatch.call_args.kwargs
    assert call["function_id"] == "claims.path.amend"
    assert call["payload"] == {
        "claim_id": 41,
        "remove_paths": ["src/unused.py"],
        "reason": "remove unused path",
        "boundary_evidence": _EVIDENCE,
    }


def test_add_paths_retains_widening_payload():
    with (
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "collect_narrow_boundary_evidence",
        ) as collect,
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "sync_local_snapshot_for_write",
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_change.dispatch_and_emit",
            return_value=0,
        ) as dispatch,
    ):
        result = claims_path_amend(
            [
                "--claim-id",
                "42",
                "--add-paths",
                "src/new.py",
                "--reason",
                "expand coverage",
                "--item",
                "YOK-9406",
            ]
        )

    assert result == 0
    collect.assert_not_called()
    assert dispatch.call_args.kwargs["payload"] == {
        "claim_id": 42,
        "add_paths": ["src/new.py"],
        "reason": "expand coverage",
        "allow_planned": False,
    }


def test_remove_paths_stops_when_snapshot_sync_does_not_complete():
    with (
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "collect_narrow_boundary_evidence",
            return_value=_EVIDENCE,
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_change."
            "sync_local_snapshot_for_write",
            return_value={"status": "failed", "message": "relay unavailable"},
        ),
        patch(
            "yoke_cli.commands.adapters.claims_path_change.dispatch_and_emit",
        ) as dispatch,
    ):
        result = claims_path_amend(
            [
                "--claim-id",
                "43",
                "--remove-paths",
                "src/unused.py",
                "--integration-target",
                "main",
                "--reason",
                "remove unused path",
                "--item",
                "YOK-9407",
            ]
        )

    assert result == 2
    dispatch.assert_not_called()


def _git(root, *args: str) -> None:
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_boundary_evidence_reports_committed_and_dirty_paths(tmp_path):
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("value = 1\n")
    (tmp_path / "src" / "drop.py").write_text("unused = True\n")
    _git(tmp_path, "add", "src")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "src" / "keep.py").write_text("value = 2\n")
    _git(tmp_path, "add", "src/keep.py")
    _git(tmp_path, "commit", "-q", "-m", "change keep")
    (tmp_path / "scratch.txt").write_text("dirty\n")

    evidence = collect_narrow_boundary_evidence(
        repo_root=str(tmp_path),
        integration_target="main",
    )

    assert evidence["touched_paths"] == ["src/keep.py"]
    assert evidence["uncommitted_paths"] == ["scratch.txt"]
    assert (
        evidence["head_sha"]
        == subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
