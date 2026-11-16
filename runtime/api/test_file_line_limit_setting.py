"""``file_line_limit`` moves every line check and message together.

A fixture project sets the limit; each check must enforce it and print it.
Unset or unusable values fall back to the default everywhere.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain import documentation_line_limit as docs_limit
from yoke_core.domain import file_budget_sizing
from yoke_core.domain.idea_readiness_file_budget_sizing import (
    verify_file_budget_sizing,
)
from yoke_core.domain.idea_readiness_results import Issue
from yoke_core.domain.install_bundle_docs_validation import _size
from yoke_harness.git_hooks import file_line_cli, pre_commit
from yoke_harness.hooks import local_policies

CASES = [
    ("file_line_limit=200\n", 200),
    ("", DEFAULT_LIMIT),
    ("file_line_limit=not-a-number\n", DEFAULT_LIMIT),
]


def _git(repo: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                   capture_output=True)


def _project(tmp_path: Path, config: str) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / ".yoke").mkdir()
    (tmp_path / ".yoke/project.config").write_text(config)
    (tmp_path / "README.md").write_text("seed\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def _stage_new_file(repo: Path, lines: int) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src/big.py").write_text("x = 1\n" * lines)
    _git(repo, "add", "src/big.py")


@pytest.mark.parametrize(("config", "limit"), CASES)
def test_pre_commit_and_check_cli_enforce_and_print_the_limit(
    tmp_path, monkeypatch, capsys, config, limit,
) -> None:
    repo = _project(tmp_path, config)
    _stage_new_file(repo, limit)
    monkeypatch.setattr(pre_commit, "_resolve_repo_root", lambda: str(repo))
    assert pre_commit._run_file_line_check_or_block() == 0
    assert file_line_cli.main(["check", "--staged", "--repo", str(repo)]) == 0

    _stage_new_file(repo, limit + 1)
    capsys.readouterr()
    assert pre_commit._run_file_line_check_or_block() == 1
    assert f"limit {limit}, remove 1 line(s)" in capsys.readouterr().err
    assert file_line_cli.main(["check", "--staged", "--repo", str(repo)]) == 1
    assert f"limit {limit}, remove 1 line(s)" in capsys.readouterr().out


@pytest.mark.parametrize(("config", "limit"), CASES)
def test_local_write_hint_uses_the_target_repo_limit(
    tmp_path, config, limit,
) -> None:
    repo = _project(tmp_path, config)
    target = str(repo / "src/new.py")

    def hint(lines: int):
        payload = {"tool_name": "Write",
                   "tool_input": {"file_path": target, "content": "x\n" * lines}}
        return local_policies.hint_file_line(payload, None)

    assert hint(limit).additional_context == ""
    context = hint(limit + 1).additional_context
    assert f"over the {limit}-line authored-file cap" in context


def test_local_write_hint_without_a_project_uses_the_default(tmp_path) -> None:
    payload = {"tool_name": "Write", "tool_input": {
        "file_path": str(tmp_path / "loose.py"),
        "content": "x\n" * (DEFAULT_LIMIT + 1)}}
    context = local_policies.hint_file_line(
        payload, None).additional_context
    assert f"over the {DEFAULT_LIMIT}-line authored-file cap" in context


@pytest.mark.parametrize(("config", "limit"), CASES)
def test_idea_file_budget_sizing_uses_the_limit(tmp_path, config, limit) -> None:
    repo = _project(tmp_path, config)
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x\n" * 10)
    fresh = f"- `src/a.py` — current 10 lines; remaining headroom {limit - 10}; " \
        "at-or-over-limit: false; responsibility: fixture.\n"
    stale = "- `src/a.py` — current 10 lines; remaining headroom 1; " \
        "at-or-over-limit: false; responsibility: fixture.\n"

    def issues(row: str):
        spec = f"## File Budget\n\n{row}"
        return verify_file_budget_sizing(spec, repo_root=repo, issue_type=Issue)

    assert issues(fresh) == []
    (stale_issue,) = issues(stale)
    assert stale_issue.context["expected_headroom"] == limit - 10
    assert f"({limit} minus N)" in stale_issue.remediation
    assert f"({limit} minus N)" in file_budget_sizing.file_budget_remediation(limit)


@pytest.mark.parametrize(("config", "limit"), CASES)
def test_docs_checks_use_the_yoke_source_limit(
    tmp_path, monkeypatch, config, limit,
) -> None:
    source = tmp_path / "source"
    (source / docs_limit._SOURCE_MARKER).mkdir(parents=True)
    (source / ".yoke").mkdir()
    (source / ".yoke/project.config").write_text(config)
    monkeypatch.setattr(docs_limit, "_SOURCE_CHECKOUT", source)

    assert docs_limit.documentation_line_limit() == limit
    assert _size(Path("p.md"), "x\n" * limit) == []
    (refusal,) = _size(Path("p.md"), "x\n" * (limit + 1))
    assert f"exceeds {limit}" in str(refusal)


def test_docs_checks_ignore_a_checkout_without_yoke_source(
    tmp_path, monkeypatch,
) -> None:
    (tmp_path / ".yoke").mkdir()
    (tmp_path / ".yoke/project.config").write_text("file_line_limit=200\n")
    monkeypatch.setattr(docs_limit, "_SOURCE_CHECKOUT", tmp_path)
    assert docs_limit.documentation_line_limit() == DEFAULT_LIMIT
