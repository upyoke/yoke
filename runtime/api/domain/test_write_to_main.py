from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.write_to_main import (
    WriteToMainError,
    main,
    normalize_content,
    resolve_target_path,
    write_to_main,
)


@pytest.fixture
def temp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    (repo / "data" / "backlog").mkdir(parents=True)
    (repo / "ouroboros").mkdir(parents=True)
    (repo / "data" / "config").write_text("base_branch=main\n", encoding="utf-8")
    (repo / "data" / "backlog" / ".counter").write_text("0\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / ".worktrees").mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "branch", "feature/test-wt"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            str(repo / ".worktrees" / "feature-test-wt"),
            "feature/test-wt",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.chdir(repo / ".worktrees" / "feature-test-wt")
    return {
        "repo": repo.resolve(),
        "worktree": (repo / ".worktrees" / "feature-test-wt").resolve(),
    }


def test_normalize_content_matches_shell_behavior() -> None:
    assert normalize_content("hello") == "hello\n"
    assert normalize_content("hello\n\n") == "hello\n"
    assert normalize_content("") == "\n"


def test_write_to_main_uses_main_repo_root_from_worktree(temp_repo: dict[str, Path]) -> None:
    target = write_to_main(
        "append",
        "ouroboros/log.md",
        "first entry",
        cwd=str(temp_repo["worktree"]),
    )
    assert target == temp_repo["repo"] / "ouroboros" / "log.md"
    assert target.read_text(encoding="utf-8") == "first entry\n"
    assert not (temp_repo["worktree"] / "ouroboros" / "log.md").exists()


def test_write_mode_overwrites(temp_repo: dict[str, Path]) -> None:
    write_to_main("write", "data/test-output.md", "first", cwd=str(temp_repo["worktree"]))
    write_to_main("write", "data/test-output.md", "second", cwd=str(temp_repo["worktree"]))
    assert (temp_repo["repo"] / "data" / "test-output.md").read_text(encoding="utf-8") == "second\n"


def test_resolve_target_path_rejects_missing_parent(temp_repo: dict[str, Path]) -> None:
    with pytest.raises(WriteToMainError, match="Directory does not exist:"):
        resolve_target_path("missing-dir/file.txt", cwd=str(temp_repo["worktree"]))


def test_main_reports_usage_for_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["badcmd", "somefile"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "badcmd" in err
    assert "Usage:" in err


def test_main_reports_usage_for_missing_path(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["append"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "Missing file path argument" in err
    assert "Usage:" in err
