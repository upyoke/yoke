"""Git, rather than a .git substring, proves client metadata boundaries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.client_facts import write_target
from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_harness.hooks import client_write_targets as targets


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


@pytest.fixture(params=["normal", "linked", "separate"])
def checkout(tmp_path, request):
    root = tmp_path.resolve()
    repo = root / "repo"
    repo.mkdir()
    args = ["init", "--quiet"]
    if request.param == "separate":
        args += ["--separate-git-dir", str(root / "metadata")]
    git(repo, *args)
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "seed",
    )
    if request.param == "linked":
        lane = repo / ".worktrees" / "held"
        git(repo, "worktree", "add", "--quiet", "-b", "held", str(lane))
        repo = lane
    return repo


def fact(repo: Path, raw: str) -> dict:
    payload = {"cwd": str(repo), "tool_input": {"file_path": raw}}
    return write_target(targets.write_targets_fact(payload, parse_shell("")), raw)


def test_common_and_per_worktree_metadata_are_excluded(checkout):
    for flag in ("--git-common-dir", "--git-dir"):
        directory = Path(git(checkout, "rev-parse", "--path-format=absolute", flag))
        target = directory / "info" / "exclude"
        for raw in (str(target), os.path.relpath(target, checkout)):
            entry = fact(checkout, raw)
            assert entry == {"path": str(target.resolve()), "ignored": True}


def test_similar_prefix_and_dotdot_escape_are_source(checkout):
    directory = Path(
        git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    candidates = [
        str(directory) + "-source/new.py",
        str(directory / ".." / "source/new.py"),
        str(checkout / "src/.git-not-metadata.py"),
    ]
    for raw in candidates:
        assert fact(checkout, raw)["ignored"] is not True


def test_symlink_to_source_is_not_metadata(checkout):
    directory = Path(git(checkout, "rev-parse", "--path-format=absolute", "--git-dir"))
    source = checkout / "src"
    source.mkdir()
    (directory / "source-link").symlink_to(source, target_is_directory=True)
    entry = fact(checkout, str(directory / "source-link/new.py"))
    assert entry == {"path": str(source / "new.py"), "ignored": False}


def test_another_repository_source_is_not_metadata(checkout, tmp_path):
    other = tmp_path.resolve() / "other"
    other.mkdir()
    git(other, "init", "--quiet")
    assert fact(checkout, str(other / "new.py"))["ignored"] is False


def test_failed_git_probe_does_not_invent_metadata(checkout, monkeypatch):
    monkeypatch.setattr(targets, "_git", lambda *args: None)
    assert fact(checkout, str(checkout / ".git/info/exclude"))["ignored"] is None


def test_unrelated_operands_do_not_erase_ignore_proof(checkout, tmp_path):
    (checkout / ".gitignore").write_text("rendered/\n", encoding="utf-8")
    raw = str(checkout / "rendered/output.md")
    payload = {
        "cwd": str(checkout),
        "tool_input": {"command": f"cp {tmp_path}/input.md {raw}"},
    }
    facts = targets.write_targets_fact(
        payload, parse_shell(payload["tool_input"]["command"])
    )
    assert write_target(facts, raw)["ignored"] is True
