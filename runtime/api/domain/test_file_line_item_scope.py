"""Authored-file gate coverage for recorded item-base scoping."""

from __future__ import annotations

from pathlib import Path
import subprocess

from yoke_contracts.project_contract.file_line_policy import item_base_config_key
from yoke_core.domain import file_line_check


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, path: str, lines: int) -> None:
    target = repo / path
    target.write_text("x\n" * lines, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", path)


def test_inherited_oversized_file_is_reported_without_blocking(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "seed.py", 1)
    _git(tmp_path, "checkout", "-q", "-b", "item")
    _commit(tmp_path, "inherited.py", 360)
    item_base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "config", item_base_config_key("item"), item_base)
    _commit(tmp_path, "owned.py", 1)

    verdict = file_line_check.changed_files_check(
        repo_root=tmp_path, base="main", staged=False,
    )

    assert verdict.ok is True
    assert not verdict.hard_fails
    assert [row.path for row in verdict.pre_existing] == ["inherited.py"]
