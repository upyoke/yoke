"""Coverage for ``verify_file_budget_line_counts`` of the pre-handoff
readiness checks.

Split off from ``test_idea_readiness_check.py`` to keep each test module
within the file-line budget; behavior and test names are preserved so
verification stays grep-able.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT

from yoke_core.domain.idea_readiness_check import (
    verify_file_budget_line_counts,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def stub_repo_root(tmp_path, monkeypatch):
    """Stub _resolve_repo_root so module file lookups land in tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    monkeypatch.chdir(repo)
    return repo


def _write_module(repo: Path, rel: str, body: str):
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


def _budget(path: str, count: int, *, tail: str = "") -> str:
    return (
        "## File Budget\n\n"
        f"- `{path}` — current {count} lines; remaining headroom "
        f"{DEFAULT_LIMIT - count}; at-or-over-limit: "
        f"{str(count >= DEFAULT_LIMIT).lower()}; "
        f"responsibility: test fixture. {tail}"
    )


class TestVerifyFileBudgetLineCounts:
    def test_recorded_count_matches(self, stub_repo_root):
        _write_module(
            stub_repo_root,
            "runtime/api/domain/foo.py",
            "x\n" * 50,
        )
        spec = _budget("runtime/api/domain/foo.py", 50)
        issues = verify_file_budget_line_counts(spec)
        # No issue: count matches and file is under threshold.
        assert all(i.code != "STALE_LINE_COUNT" for i in issues)
        assert all(i.code != "MISSING_SIBLING_PLAN" for i in issues)

    def test_stale_count_flagged(self, stub_repo_root):
        _write_module(
            stub_repo_root,
            "runtime/api/domain/foo.py",
            "x\n" * 100,
        )
        spec = _budget("runtime/api/domain/foo.py", 200)
        issues = verify_file_budget_line_counts(spec)
        assert any(i.code == "STALE_LINE_COUNT" for i in issues)

    def test_at_cap_without_sibling_plan_flagged(self, stub_repo_root):
        _write_module(
            stub_repo_root,
            "runtime/api/domain/big.py",
            "x\n" * 340,
        )
        spec = _budget("runtime/api/domain/big.py", 340)
        issues = verify_file_budget_line_counts(spec)
        assert any(i.code == "MISSING_SIBLING_PLAN" for i in issues)

    def test_at_cap_with_sibling_plan_passes(self, stub_repo_root):
        _write_module(
            stub_repo_root,
            "runtime/api/domain/big.py",
            "x\n" * 340,
        )
        spec = _budget(
            "runtime/api/domain/big.py", 340,
            tail="Plan: extract to a new sibling module big_helper.py.",
        )
        issues = verify_file_budget_line_counts(spec)
        assert all(i.code != "MISSING_SIBLING_PLAN" for i in issues)

    def test_inconsistent_headroom_and_flag_are_flagged(self, stub_repo_root):
        _write_module(stub_repo_root, "runtime/api/domain/foo.py", "x\n" * 50)
        spec = (
            "## File Budget\n\n- `runtime/api/domain/foo.py` — current 50 lines; "
            "remaining headroom 0; at-or-over-limit: true; responsibility: x."
        )

        issues = verify_file_budget_line_counts(spec)

        assert any(i.code == "STALE_FILE_BUDGET_SIZING" for i in issues)
