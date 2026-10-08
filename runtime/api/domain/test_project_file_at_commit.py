"""Reading a project file at an exact commit, checkout first, provider second."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import project_checkout_locations, project_file_at_commit
from yoke_core.domain.project_file_at_commit import (
    ProjectFileAbsent,
    ProjectFileUnreadable,
    read_project_file,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "qa@example.test")
    _git(tmp_path, "config", "user.name", "QA")
    return tmp_path


def _commit(repo: Path, text: str) -> str:
    (repo / "pin.txt").write_text(text, encoding="utf-8")
    _git(repo, "add", "pin.txt")
    _git(repo, "commit", "-q", "-m", text)
    return _git(repo, "rev-parse", "HEAD")


def _registered(monkeypatch, checkout: Path | None) -> None:
    monkeypatch.setattr(
        project_checkout_locations, "checkout_for_project_id", lambda _id: checkout
    )


def test_checkout_answers_the_file_at_that_commit_not_the_tip(repo, monkeypatch):
    first = _commit(repo, "0.1.1+launch.590\n")
    _commit(repo, "0.1.1+launch.591\n")
    _registered(monkeypatch, repo)

    assert read_project_file(None, 7, first, "pin.txt") == b"0.1.1+launch.590\n"


def test_commit_without_the_file_is_absent(repo, monkeypatch):
    sha = _commit(repo, "x\n")
    _registered(monkeypatch, repo)

    with pytest.raises(ProjectFileAbsent, match="does not carry missing.txt"):
        read_project_file(None, 7, sha, "missing.txt")


def test_unknown_commit_falls_through_to_the_provider(repo, monkeypatch):
    _commit(repo, "x\n")
    _registered(monkeypatch, repo)
    asked: list[str] = []

    def provider(conn, project_id, sha, path):
        asked.append(sha)
        return b"0.1.1+launch.590\n"

    monkeypatch.setattr(project_file_at_commit, "_from_provider", provider)

    assert read_project_file(None, 7, "d" * 40, "pin.txt") == b"0.1.1+launch.590\n"
    assert asked == ["d" * 40]


def test_no_source_names_every_reason(monkeypatch):
    _registered(monkeypatch, None)

    def provider(conn, project_id, sha, path):
        raise ProjectFileUnreadable("binding revoked")

    monkeypatch.setattr(project_file_at_commit, "_from_provider", provider)

    with pytest.raises(ProjectFileUnreadable) as exc:
        read_project_file(None, 7, "d" * 40, "pin.txt")
    assert "no checkout of this project is registered" in str(exc.value)
    assert "binding revoked" in str(exc.value)
