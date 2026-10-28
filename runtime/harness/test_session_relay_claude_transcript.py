"""Claude transcript path helpers for stopped-session wake."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_harness.session_relay_claude_transcript import (
    claude_project_storage_key,
    claude_session_transcript_exists,
    claude_session_transcript_path,
)


def test_project_storage_key_replaces_path_separators(tmp_path: Path) -> None:
    checkout = tmp_path / "repo" / "nested"
    checkout.mkdir(parents=True)
    assert claude_project_storage_key(checkout).endswith("repo-nested")


@pytest.mark.parametrize(
    ("checkout", "expected"),
    [
        ("/a/b/nested", "-a-b-nested"),
        ("/a/b/.worktrees/X", "-a-b--worktrees-X"),
        ("/a/.claude/worktrees/y", "-a--claude-worktrees-y"),
        ("/a/repo_name with space", "-a-repo-name-with-space"),
        ("/a/é😀", "-a----"),
        ("/a/" + "x" * 197, "-a-" + "x" * 197),
        ("/a/" + "x" * 198, "-a-" + "x" * 197 + "-bz3asj"),
        ("/a/" + "x" * 199, "-a-" + "x" * 197 + "-g2a0lh"),
        ("/a/" + "long_name. " * 25, ("-a-" + "long-name--" * 25)[:200] + "-r4ieb"),
        ("/a/" + "😀" * 101, "-a" + "-" * 198 + "-dygf9w"),
    ],
)
def test_project_storage_key_matches_claude(checkout: str, expected: str) -> None:
    assert claude_project_storage_key(Path(checkout)) == expected


def test_transcript_path_uses_home_projects_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_transcript.Path.home",
        lambda: tmp_path,
    )
    checkout = tmp_path / ".worktrees" / "repo_name with space"
    checkout.mkdir(parents=True)
    session_id = "87654321-4321-4321-8321-cba987654321"
    expected = (
        tmp_path
        / ".claude"
        / "projects"
        / claude_project_storage_key(checkout)
        / f"{session_id}.jsonl"
    )
    assert claude_session_transcript_path(checkout, session_id) == expected


def test_transcript_exists_checks_file_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_transcript.Path.home",
        lambda: tmp_path,
    )
    checkout = tmp_path / ".worktrees" / "repo_name with space"
    checkout.mkdir(parents=True)
    session_id = "87654321-4321-4321-8321-cba987654321"
    transcript = claude_session_transcript_path(checkout, session_id)
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}", encoding="utf-8")

    assert claude_session_transcript_exists(checkout, session_id) is True
    assert claude_session_transcript_exists(checkout, "missing-session") is False
