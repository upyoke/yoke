"""Doctor reconciles terminal lanes with the shared cleanup proof."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from runtime.api.engines._doctor_hc_git_test_helpers import (
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


def _release_lane_row(conn, lane_id: int, item_id: int, path: Path) -> None:
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id, item_id, branch, path, lane_role, state, created_at, updated_at, released_at) "
        "VALUES (%s, %s, %s, %s, 'implementation', 'released', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z')",
        (lane_id, item_id, path.name, str(path)),
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
    nested = repo / "webapp"
    nested.mkdir()
    (nested / ".gitignore").write_text("generated/\n", encoding="utf-8")
    _git(repo, "add", "base.txt", "webapp/.gitignore")
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
    generated = lane / "webapp" / "generated" / "bundle.js"
    generated.parent.mkdir()
    generated.write_text("built\n", encoding="utf-8")
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


def test_doctor_fix_preserves_and_names_unignored_content(tmp_path, monkeypatch):
    repo, lane = _terminal_lane(tmp_path)
    scratch = lane / "operator-note.txt"
    scratch.write_text("keep\n", encoding="utf-8")
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
        fixed = _run_hc(hc_worktree_health, conn, fix=True)

    assert _result(fixed).result == "WARN"
    assert "operator-note.txt" in _result(fixed).detail
    assert scratch.read_text(encoding="utf-8") == "keep\n"
    assert lane.exists()


def _doctor_patches(repo: Path):
    return (
        patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(repo),
        ),
        patch(
            "yoke_core.engines.doctor_hc_worktrees_health._authority_block",
            return_value="",
        ),
    )


def test_doctor_rolls_up_released_lanes_still_on_disk_with_reasons(
    tmp_path, monkeypatch
):
    """One line says what needs an operator: dirty, locked, unregistered."""
    repo, lane = _terminal_lane(tmp_path)
    (lane / "wip.txt").write_text("keep\n", encoding="utf-8")
    (lane / "more.txt").write_text("keep\n", encoding="utf-8")
    stray = repo / ".worktrees" / "YOK-21"
    stray.mkdir()
    conn = _make_conn()
    _insert_item(conn, 20, "Done", workflow_id="issue", status="done")
    _insert_item(conn, 21, "Done too", workflow_id="issue", status="done")
    _release_lane_row(conn, 1, 20, lane)
    _release_lane_row(conn, 2, 21, stray)
    conn.commit()
    monkeypatch.chdir(repo)
    root_patch, authority_patch = _doctor_patches(repo)

    with root_patch, authority_patch:
        detected = _run_hc(hc_worktree_health, conn)

    detail = _result(detected).detail
    assert _result(detected).result == "WARN"
    assert detail.splitlines()[0] == (
        "- 2 released lanes still on disk: dirty (YOK-20: 2 modified files), "
        "unregistered directory (YOK-21)"
    )
    assert "worktree is dirty (2 modified files)" in detail
    assert stray.exists()


def test_doctor_names_a_locked_lane_and_fix_leaves_it(tmp_path, monkeypatch):
    repo, lane = _terminal_lane(tmp_path)
    _git(repo, "worktree", "lock", "--reason", "initializing", str(lane))
    conn = _make_conn()
    _insert_item(conn, 20, "Done", workflow_id="issue", status="done")
    _release_lane_row(conn, 1, 20, lane)
    conn.commit()
    monkeypatch.chdir(repo)
    root_patch, authority_patch = _doctor_patches(repo)

    with root_patch, authority_patch:
        fixed = _run_hc(hc_worktree_health, conn, fix=True)

    detail = _result(fixed).detail
    assert _result(fixed).result == "WARN"
    assert detail.splitlines()[0] == (
        "- 1 released lane still on disk: locked (YOK-20: initializing)"
    )
    assert "worktree is locked (initializing)" in detail
    assert lane.exists()


def test_doctor_counts_a_clean_lane_as_sweep_ready(tmp_path, monkeypatch):
    repo, lane = _terminal_lane(tmp_path)
    conn = _make_conn()
    _insert_item(conn, 20, "Done", workflow_id="issue", status="done")
    _release_lane_row(conn, 1, 20, lane)
    conn.commit()
    monkeypatch.chdir(repo)
    root_patch, authority_patch = _doctor_patches(repo)

    with root_patch, authority_patch:
        detected = _run_hc(hc_worktree_health, conn)

    detail = _result(detected).detail
    assert detail.splitlines()[0] == (
        "- 1 released lane still on disk: sweep-ready (YOK-20)"
    )
    assert "the next landing on this machine sweeps it" in detail
