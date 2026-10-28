"""Readiness blocks scoped files that the File Budget does not list."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.idea_readiness_observation_admission import admit_issues
from yoke_core.domain.idea_readiness_results import Issue
from yoke_core.domain.idea_readiness_scope_budget import (
    SCOPED_PATH_NOT_IN_FILE_BUDGET,
    budget_row,
    verify_scoped_paths_in_file_budget,
)

_LISTED = "pkg/listed.py"
_MISSING = "pkg/missing.py"


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / _LISTED).write_text("a\n" * 10, encoding="utf-8")
    (tmp_path / _MISSING).write_text("b\n" * 12, encoding="utf-8")
    (tmp_path / "pkg/prose_only.py").write_text("c\n", encoding="utf-8")
    return tmp_path


def _spec(section: str, *, budget_rows: list[str] | None) -> str:
    text = (
        f"## {section}\n\n"
        f"1. Edit `{_MISSING}:12,16` and `{_LISTED}:4-9`.\n"
        f"- Edit `{_LISTED}` again.\n"
        "Prose names `pkg/prose_only.py`.\n"
        "- Mirror `pkg/install_bundle_tree/pkg/listed.py`.\n"
        "- Create `pkg/new_module.py`.\n"
    )
    if budget_rows is not None:
        text += "\n## File Budget\n\n" + "\n".join(budget_rows) + "\n"
    return text


def _check(spec: str, repo: Path) -> list[Issue]:
    return verify_scoped_paths_in_file_budget(
        spec, repo_root=repo, issue_type=Issue,
    )


def test_missing_scoped_row_blocks_with_count_and_row(tmp_path):
    repo = _repo(tmp_path)
    spec = _spec("Change", budget_rows=[budget_row(_LISTED, 10)])

    issues = _check(spec, repo)

    assert [i.code for i in issues] == [SCOPED_PATH_NOT_IN_FILE_BUDGET]
    row = (
        f"- `{_MISSING}` — current 12 lines; remaining headroom 338; "
        "at-or-over-limit: false; responsibility: <what this item changes here>."
    )
    assert issues[0].context == {"path": _MISSING, "lines": 12, "row": row}
    assert row in issues[0].remediation


def test_every_scope_row_present_passes(tmp_path):
    repo = _repo(tmp_path)
    spec = _spec(
        "Fix",
        budget_rows=[budget_row(_LISTED, 10), budget_row(_MISSING, 12)],
    )

    assert _check(spec, repo) == []


def test_context_sections_are_not_scope(tmp_path):
    repo = _repo(tmp_path)
    for section in ("Cause", "Tests"):
        spec = _spec(section, budget_rows=[budget_row(_LISTED, 10)])
        assert _check(spec, repo) == []


def test_spec_without_file_budget_is_not_checked(tmp_path):
    repo = _repo(tmp_path)

    assert _check(_spec("Change", budget_rows=None), repo) == []


def test_host_without_checkout_admits_reported_issue(tmp_path):
    repo = _repo(tmp_path)
    spec = _spec("Scope", budget_rows=[budget_row(_LISTED, 10)])
    payloads = [
        {"code": i.code, "message": i.message,
         "remediation": i.remediation, "context": i.context}
        for i in _check(spec, repo)
    ]

    admitted, rejected = admit_issues(payloads, spec_text=spec)

    assert rejected == []
    assert [i.context["path"] for i in admitted] == [_MISSING]


def test_host_without_checkout_rejects_path_outside_scope(tmp_path):
    spec = _spec("Change", budget_rows=[budget_row(_LISTED, 10)])
    payload = {
        "code": SCOPED_PATH_NOT_IN_FILE_BUDGET, "message": "m",
        "remediation": "r", "context": {"path": "pkg/other.py"},
    }

    admitted, rejected = admit_issues([payload], spec_text=spec)

    assert admitted == []
    assert rejected[0]["code"] == SCOPED_PATH_NOT_IN_FILE_BUDGET
