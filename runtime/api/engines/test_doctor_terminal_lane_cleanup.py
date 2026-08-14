"""Doctor reconciles terminal lanes with the shared cleanup proof."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from yoke_core.engines._doctor_hc_git_test_helpers import (
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines.doctor import hc_worktree_health


BRANCH = "YOK-20"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _terminal_lane(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    lane = repo / ".worktrees" / BRANCH
    _git(repo, "worktree", "add", "-b", BRANCH, str(lane))
    (lane / "change.txt").write_text("change\n", encoding="utf-8")
    _git(lane, "add", "change.txt")
    _git(lane, "commit", "-m", "change")
    _git(repo, "merge", "--no-edit", BRANCH)
    return repo, lane


def test_doctor_reports_and_fixes_only_a_verified_safe_terminal_lane(
    tmp_path,
    monkeypatch,
):
    repo, lane = _terminal_lane(tmp_path)
    conn = _make_conn()
    _insert_item(conn, 20, "Done", workflow_id="issue", status="done")
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id, item_id, branch, path, lane_role, state, created_at, updated_at, released_at) "
        "VALUES (1, 20, %s, %s, 'implementation', 'released', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z')",
        (BRANCH, str(lane)),
    )
    conn.commit()
    monkeypatch.chdir(repo)

    with (
        patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(repo),
        ),
        patch(
            "yoke_core.engines.doctor_hc_worktrees_health._authority_block",
            return_value="",
        ),
    ):
        detected = _run_hc(hc_worktree_health, conn)
        fixed = _run_hc(hc_worktree_health, conn, fix=True)

    assert _result(detected).result == "WARN"
    assert "verified-safe" in _result(detected).detail
    assert _result(fixed).result == "PASS"
    assert "Fixed: removed terminal lane" in _result(fixed).detail
    assert not lane.exists()
    assert _git(repo, "branch", "--list", BRANCH).stdout.strip() == ""
