"""Repository identity scopes main-commit decisions without local server Git."""

from types import SimpleNamespace

import pytest

from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.repo_paths import normalize_repo_path
from yoke_contracts.runtime_ports import structured_dispatch
from yoke_core.domain import lint_main_commit
from yoke_core.domain.lint_session_cwd_path_authority import (
    repo_root_from_worktree_path,
)
from runtime.api.domain.lint_main_commit_test_support import (
    _evaluate_payload,
    _payload,
    git_facts,
)


@pytest.mark.parametrize(
    ("commit_root", "lane", "denied"),
    [
        ("/tmp/scratch", "/project/.worktrees/item", False),
        ("/project", "/project/.worktrees/item", True),
        ("/project/", "/project/.worktrees/item", True),
        (r"C:\x\repo", "c:/x/repo/.worktrees/item", True),
        ("c:/x/repo", r"C:\x\repo\.worktrees\item", True),
        ("/project", "/project-other/.worktrees/item", False),
        (None, "/project/.worktrees/item", False),
        ("", "/project/.worktrees/item", False),
    ],
)
def test_decision_only_names_items_in_commit_repo(monkeypatch, commit_root, lane, denied):
    ref = "TEST-1"
    rows = [
        {"public_ref": ref, "title": "Matching", "worktrees": [{"path": lane}]},
        {"public_ref": "OTHER-2", "title": "Elsewhere",
         "worktrees": [{"path": "/elsewhere/.worktrees/item"}]},
        {"public_ref": "OLD-3", "terminal": True,
         "worktrees": [{"path": lane}]},
        {"public_ref": "NONE-4", "worktrees": []},
    ]
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, result={"rows": rows})

    monkeypatch.setattr(
        structured_dispatch, "get_structured_dispatch",
        lambda: SimpleNamespace(call_dispatcher=dispatch),
    )
    facts = git_facts("main", ["source.py"])
    if commit_root is None:
        facts[CLIENT_GIT_COMMIT_FACTS_KEY].pop("repo_root")
    else:
        facts[CLIENT_GIT_COMMIT_FACTS_KEY]["repo_root"] = commit_root
    reason = _evaluate_payload(_payload("git commit -m change", facts))
    assert (reason is not None) is denied
    if denied:
        assert ref in reason
        assert "OTHER-2" not in reason
        assert "OLD-3" not in reason
        assert "NONE-4" not in reason
    assert len(calls) == (1 if commit_root else 0)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/repo/.worktrees/item", "/repo"),
        (r"C:\Repo\.worktrees\item", "c:/Repo"),
        ("/.worktrees/item", "/"),
        ("/repo/.worktrees-other/item", None),
        ("/repo", None),
    ],
)
def test_lane_root_is_portable(path, expected):
    assert repo_root_from_worktree_path(path) == expected


def test_normalizer_preserves_path_case():
    assert normalize_repo_path(r"C:\Repo/" ) == "c:/Repo"
