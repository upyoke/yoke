# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import worktree_preflight as wp

from yoke_core.domain import worktree_preflight_steps as steps


def _build_repo_layout(tmp_path):
    """Build a minimal git-initialized repo+worktree layout for orchestrator tests."""
    import subprocess

    repo = tmp_path / "main"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        capture_output=True,
    )
    worktrees = repo / ".worktrees"
    worktree = worktrees / "YOK-9001"
    worktrees.mkdir(parents=True)
    worktree.mkdir()
    return SimpleNamespace(
        root=str(repo),
        worktree=str(worktree),
        worktrees=str(worktrees),
    )


@pytest.fixture
def repo_layout(tmp_path):
    return _build_repo_layout(tmp_path)


def _patch_steps(
    monkeypatch,
    *,
    claim_outcome=(True, "(already owned)"),
    activate_outcome=(True, "", [39]),
    dirty_outcome=(False, "", []),
    create_result=None,
    branch_and_lane=("YOK-9001", None),
):
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **kwargs: SimpleNamespace(
            success=True, result={"item": {"public_ref": "YOK-9001"}}, error=None
        ),
    )
    # Naming has its own coverage in test_worktree_public_ref_naming and now
    # refuses rather than inventing a name, so it is patched like the rest.
    monkeypatch.setattr(
        wp, "resolve_item_branch_and_lane", lambda item_id: branch_and_lane
    )
    monkeypatch.setattr(wp, "claim_work", lambda item_id: claim_outcome)
    monkeypatch.setattr(wp, "activate_path_claims", lambda item_id: activate_outcome)
    blocked, kind, paths = dirty_outcome
    verdict = SimpleNamespace(
        blocked=blocked,
        kind=kind,
        paths=paths,
        needed_paths=tuple(paths),
        narrative=(
            "Cannot create worktree: overlapping files.\n  - " + "\n  - ".join(paths)
            if blocked
            else ""
        ),
        warning_note="",
        source_root_prefixes=(),
    )
    monkeypatch.setattr(
        wp, "evaluate_dirty_main_for_item", lambda *_args, **_kwargs: verdict
    )
    if create_result is not None:
        from yoke_core.domain import worktree_create

        def _fake_create(**kwargs):
            return create_result

        monkeypatch.setattr(worktree_create, "create_worktree", _fake_create)
