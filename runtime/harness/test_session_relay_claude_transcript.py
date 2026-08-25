"""Claude transcript path helpers for stopped-session wake."""

from __future__ import annotations

from pathlib import Path

from yoke_harness.session_relay_claude_transcript import (
    claude_project_storage_key,
    claude_session_transcript_exists,
    claude_session_transcript_path,
)


def test_project_storage_key_replaces_path_separators(tmp_path: Path) -> None:
    checkout = tmp_path / "repo" / "nested"
    checkout.mkdir(parents=True)
    assert claude_project_storage_key(checkout).endswith("repo-nested")


def test_transcript_path_uses_home_projects_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_transcript.Path.home",
        lambda: tmp_path,
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
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
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    session_id = "87654321-4321-4321-8321-cba987654321"
    transcript = claude_session_transcript_path(checkout, session_id)
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}", encoding="utf-8")

    assert claude_session_transcript_exists(checkout, session_id) is True
    assert claude_session_transcript_exists(checkout, "missing-session") is False
