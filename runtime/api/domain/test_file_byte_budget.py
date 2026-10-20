"""Per-file byte budgets fail both authored-file checkers on growth."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_contracts.project_contract.file_byte_budget import parse_byte_budgets
from yoke_core.domain import file_line_check as core_check
from yoke_core.domain.git_pre_commit import _format_file_line_summary
from yoke_harness.git_hooks import file_line_check as harness_check

CHECKERS = pytest.mark.parametrize(
    "checker",
    [core_check, harness_check],
    ids=["source-dev", "product-safe"],
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path, budget_line: str) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".yoke").mkdir()
    (tmp_path / ".yoke" / "project.config").write_text(budget_line + "\n")
    (tmp_path / "AGENTS.md").write_text("rule\n" * 10)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    _git(tmp_path, "checkout", "-q", "-b", "item")
    return tmp_path


def _grow(repo: Path, size: int) -> None:
    (repo / "AGENTS.md").write_text("x" * (size - 1) + "\n")
    _git(repo, "add", "AGENTS.md")


@CHECKERS
def test_growth_past_budget_fails_with_named_reason_and_recovery(tmp_path, checker):
    repo = _repo(tmp_path, "file_byte_budget=AGENTS.md:100")
    _grow(repo, 140)
    _git(repo, "commit", "-q", "-m", "grow")

    verdict = checker.changed_files_check(repo_root=repo, base="main")

    assert verdict.ok is False
    [failure] = verdict.byte_budget_fails
    assert failure.reason == "file_byte_budget_exceeded"
    assert "140 bytes, budget 100 (over by 40)" in failure.detail
    assert "move the text to the one surface that owns it" in failure.detail
    assert "byte-budget failure" in verdict.summary


@CHECKERS
def test_staged_growth_blocks_the_commit(tmp_path, checker):
    repo = _repo(tmp_path, "file_byte_budget=AGENTS.md:100")
    _grow(repo, 101)

    verdict = checker.changed_files_check(repo_root=repo, staged=True)

    assert verdict.ok is False
    assert [f.path for f in verdict.byte_budget_fails] == ["AGENTS.md"]
    summary = _format_file_line_summary(verdict, limit=350)
    assert "Byte-budget fails:" in summary
    assert "BYTE-BUDGET  AGENTS.md: file_byte_budget_exceeded" in summary


@CHECKERS
def test_change_within_budget_passes(tmp_path, checker):
    repo = _repo(tmp_path, "file_byte_budget=AGENTS.md:100")
    _grow(repo, 100)

    verdict = checker.changed_files_check(repo_root=repo, staged=True)

    assert verdict.ok is True
    assert verdict.byte_budget_fails == []


@CHECKERS
def test_budget_for_a_missing_file_is_stale_config(tmp_path, checker):
    repo = _repo(tmp_path, "file_byte_budget=gone.md:100")
    _grow(repo, 50)

    verdict = checker.changed_files_check(repo_root=repo, staged=True)

    assert verdict.ok is False
    assert [f.reason for f in verdict.byte_budget_fails] == ["file_byte_budget_stale"]


def test_malformed_and_duplicate_entries_are_reported():
    budgets, broken = parse_byte_budgets(
        ["AGENTS.md:100", "AGENTS.md:200", "docs/x.md", "docs/y.md:0"],
    )

    assert budgets == {"AGENTS.md": 100}
    assert [f.reason for f in broken] == [
        "file_byte_budget_duplicate",
        "file_byte_budget_malformed",
        "file_byte_budget_malformed",
    ]
