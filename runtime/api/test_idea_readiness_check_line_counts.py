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
    """A throwaway checkout the sizing check reads files from."""
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
        issues = verify_file_budget_line_counts(spec, repo_root=stub_repo_root)
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
        issues = verify_file_budget_line_counts(spec, repo_root=stub_repo_root)
        assert any(i.code == "STALE_LINE_COUNT" for i in issues)

    def test_at_cap_without_sibling_plan_flagged(self, stub_repo_root):
        _write_module(
            stub_repo_root,
            "runtime/api/domain/big.py",
            "x\n" * 340,
        )
        spec = _budget("runtime/api/domain/big.py", 340)
        issues = verify_file_budget_line_counts(spec, repo_root=stub_repo_root)
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
        issues = verify_file_budget_line_counts(spec, repo_root=stub_repo_root)
        assert all(i.code != "MISSING_SIBLING_PLAN" for i in issues)

    def test_inconsistent_headroom_and_flag_are_flagged(self, stub_repo_root):
        _write_module(stub_repo_root, "runtime/api/domain/foo.py", "x\n" * 50)
        spec = (
            "## File Budget\n\n- `runtime/api/domain/foo.py` — current 50 lines; "
            "remaining headroom 0; at-or-over-limit: true; responsibility: x."
        )

        issues = verify_file_budget_line_counts(spec, repo_root=stub_repo_root)

        assert any(i.code == "STALE_FILE_BUDGET_SIZING" for i in issues)


@pytest.mark.parametrize(("spec", "expected_code"), [
    ("No budget declared.", "MISSING_FILE_BUDGET"),
    ("## File Budget\n\n| Path | Lines |\n| --- | --- |\n"
     "| `src/example.py` | 120 |", "MISSING_FILE_BUDGET"),
    ("## File Budget\n\n- `src/example.py`", "MISSING_FILE_BUDGET_SIZING"),
    ("## File Budget\n\n- `src/example.py` — current 120 lines; "
     "remaining headroom 0; at-or-over-limit: true", "STALE_FILE_BUDGET_SIZING"),
])
def test_budget_refusals_teach_complete_row_format(
    spec, expected_code, test_db, stub_repo_root, monkeypatch,
):
    import json

    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain import idea_readiness_check

    item_id = 4951
    insert_item(
        test_db, id=item_id, workflow_id="dash", status="idea", spec=spec,
        workflow_posture=json.dumps({"file_budget": True}),
    )
    monkeypatch.setattr(
        idea_readiness_check, "item_project_checkout", lambda *_: stub_repo_root,
    )
    outcome = idea_readiness_check.run_all_checks(test_db, item_id)
    issue = next(i for i in outcome.issues if i.code == expected_code)
    for rule in (
        "dash list", "each path in backticks", "current N lines",
        "350 minus N", "at-or-over-limit: true|false", "N >= 350",
        "new files use current 0 lines", "each generated copy as its own row",
        "every path in the claim when path claims are enabled",
        "- `src/example.py` — current 120 lines; remaining headroom 230; "
        "at-or-over-limit: false",
    ):
        assert rule in issue.remediation
