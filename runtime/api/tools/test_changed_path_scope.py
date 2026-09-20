"""Coverage for the changed-path scope local CI mirrors share.

The point of these tests is the property that makes a local mirror worth
running: the set it checks is the set the required CI contract will check.
"""

from __future__ import annotations

import pathlib
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.project_contract.changed_path_scope import (
    staged_changed_paths,
    untracked_paths,
    working_tree_changed_paths,
)
from yoke_core.domain import file_line_check
from yoke_core.tools import ci_repo_contracts, ruff_changed


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _repo_with_baseline(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_untracked_authored_file_joins_the_changed_set(tmp_path: Path) -> None:
    repo, base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    (repo / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")

    scope = working_tree_changed_paths(repo, base)

    assert scope.tracked == ("tracked.py",)
    assert scope.untracked == ("authored.py",)
    assert scope.paths == ("tracked.py", "authored.py")


def test_ignored_paths_stay_out_of_the_changed_set(tmp_path: Path) -> None:
    repo, base = _repo_with_baseline(
        tmp_path, {"tracked.py": "value = 1\n", ".gitignore": "ignored/\n"},
    )
    (repo / "ignored").mkdir()
    (repo / "ignored" / "generated.py").write_text("noise = 1\n", encoding="utf-8")
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")

    assert untracked_paths(repo) == ("authored.py",)
    assert "ignored/generated.py" not in working_tree_changed_paths(repo, base).paths


def test_staged_scope_carries_no_untracked_half(tmp_path: Path) -> None:
    repo, _base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")
    _git(repo, "add", "authored.py")
    (repo / "unstaged_new.py").write_text("later = True\n", encoding="utf-8")

    assert staged_changed_paths(repo) == ("authored.py",)


def test_coverage_sentence_names_both_halves_and_the_exclusions(
    tmp_path: Path,
) -> None:
    repo, base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    (repo / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")

    sentence = working_tree_changed_paths(repo, base).coverage_sentence()

    assert "1 tracked path changed" in sentence
    assert "1 untracked path" in sentence
    assert "ignored paths and deletions stay out" in sentence


def test_local_scope_matches_the_set_ci_derives_for_the_same_work(
    tmp_path: Path,
) -> None:
    """A green local mirror has to mean the CI contract saw the same files."""
    repo, base = _repo_with_baseline(
        tmp_path, {"tracked.py": "value = 1\n", "untouched.py": "value = 1\n"},
    )
    (repo / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "staged.py").write_text("staged = True\n", encoding="utf-8")
    _git(repo, "add", "staged.py")
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")

    local = set(working_tree_changed_paths(repo, base).paths)

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "the same work, committed")
    from_ci = set(ci_repo_contracts.resolve_changed_path_scope(repo, base).paths)

    assert local == from_ci


def test_untracked_python_reaches_the_lint_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo, _base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    (repo / "authored.py").write_text(
        'message = f"no placeholder"\n', encoding="utf-8",
    )
    linted: list[tuple[str, ...]] = []

    def _record(_root: Path, _arguments, paths) -> int:
        linted.append(tuple(paths))
        return 0

    monkeypatch.setattr(ruff_changed, "_run_ruff", _record)

    assert ruff_changed.run("main", root=repo) == 0
    assert linted == [("authored.py",)]


def test_lint_result_names_what_its_scope_covered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    (repo / "tracked.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "authored.py").write_text("fresh = True\n", encoding="utf-8")
    monkeypatch.setattr(ruff_changed, "_run_ruff", lambda *_args: 0)

    assert ruff_changed.run("main", root=repo) == 0

    printed = capsys.readouterr().out
    assert "1 tracked Python file changed" in printed
    assert "1 untracked Python file" in printed


def test_empty_result_still_names_its_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    repo, _base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})

    assert ruff_changed.run("main", root=repo) == 0

    printed = capsys.readouterr().out
    assert "no changed Python files" in printed
    assert "0 untracked Python files" in printed


def test_authored_file_limit_sees_an_untracked_over_limit_file(
    tmp_path: Path,
) -> None:
    repo, base = _repo_with_baseline(tmp_path, {"tracked.py": "value = 1\n"})
    limit = file_line_check.resolved_policy(pathlib.Path(repo)).limit
    (repo / "oversized.py").write_text(
        "".join(f"value_{index} = {index}\n" for index in range(limit + 10)),
        encoding="utf-8",
    )

    verdict = file_line_check.changed_files_check(
        repo_root=pathlib.Path(repo), base=base, staged=False,
    )

    assert not verdict.ok
    assert [change.path for change in verdict.hard_fails] == ["oversized.py"]
    assert "1 untracked path" in verdict.summary
