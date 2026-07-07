"""Renderer-side tests for yoke_core.domain.populate_registry_render.

Covers the ``_resolve_repo_root`` env-var precedence chain — including the
YOK-1704 hotfix guard that YOKE_ROOT pointing at a linked worktree must
not be silently re-anchored to the owning main checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_resolve_repo_root_normalizes_repo_root_yoke_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from yoke_core.domain.populate_registry import _resolve_repo_root

    repo_root = tmp_path / "repo"
    (repo_root / "data").mkdir(parents=True)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(repo_root))

    assert _resolve_repo_root() == repo_root.resolve()


def test_resolve_repo_root_accepts_state_dir_yoke_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from yoke_core.domain.populate_registry import _resolve_repo_root

    repo_root = tmp_path / "repo"
    state_dir = repo_root / "data"
    state_dir.mkdir(parents=True)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(state_dir))

    assert _resolve_repo_root() == repo_root.resolve()


def test_resolve_repo_root_preserves_worktree_path_yoke_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """YOKE_ROOT pointing at a linked worktree must NOT strip the
    ``.worktrees/<branch>/`` segment. The docs renderer needs the output
    anchored where the agent is actually editing — silently re-anchoring
    to main caused stale catalog regenerations to land in main's tree
    from worktree-only registry edits."""
    from yoke_core.domain.populate_registry import _resolve_repo_root

    main_root = tmp_path / "main"
    worktree_root = main_root / ".worktrees" / "YOK-9999"
    (worktree_root / "data").mkdir(parents=True)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("YOKE_ROOT", str(worktree_root))

    resolved = _resolve_repo_root()
    assert resolved == worktree_root.resolve()
    assert ".worktrees" in resolved.parts
