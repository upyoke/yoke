"""Sentinel tests for the agents_render workspace anchor.

Locks the structural contracts that prevent the leak shape:

- ``write_all`` and ``write_all_claude`` raise ``TypeError`` when called
  without ``target_root``.
- ``resolve_target_root_for_cli`` honors the ``--target-root`` argument
  and ``$YOKE_RENDER_TARGET_ROOT`` env var, and refuses to fall back to
  ``_repo_root`` when called from a linked worktree without an explicit
  anchor.

Write-time authority enforcement is owned by
``workspace_authority.assert_target_under_session_work_authority``. Its
work-claim refusal regression lives in
:mod:`test_agents_render_workspace_anchor` and its own
behaviour matrix is covered by :mod:`test_workspace_authority`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.agents_render import (
    write_all,
    write_all_claude,
)
from yoke_core.domain.agents_render_workspace import (
    RENDER_TARGET_ROOT_ENV_VAR,
    resolve_target_root_for_cli,
)


# ---------------------------------------------------------------------------
# API contract on writers
# ---------------------------------------------------------------------------


def test_write_all_requires_target_root() -> None:
    """``write_all()`` without ``target_root`` raises ``TypeError``."""
    with pytest.raises(TypeError):
        write_all()  # type: ignore[call-arg]


def test_write_all_claude_requires_target_root() -> None:
    """``write_all_claude()`` without ``target_root`` raises ``TypeError``."""
    with pytest.raises(TypeError):
        write_all_claude()  # type: ignore[call-arg]


def test_write_all_target_root_must_be_keyword() -> None:
    """``write_all`` rejects positional ``target_root`` — keyword-only."""
    with pytest.raises(TypeError):
        write_all(Path("/tmp"))  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CLI target-root resolution precedence + linked-worktree refusal
# ---------------------------------------------------------------------------


def test_resolve_target_root_for_cli_prefers_arg_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv(RENDER_TARGET_ROOT_ENV_VAR, str(tmp_path / "from-env"))
    chosen = tmp_path / "from-arg"
    chosen.mkdir()
    resolved = resolve_target_root_for_cli(str(chosen))
    assert resolved == chosen.resolve()


def test_resolve_target_root_for_cli_uses_env_var_when_arg_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    chosen = tmp_path / "from-env"
    chosen.mkdir()
    monkeypatch.setenv(RENDER_TARGET_ROOT_ENV_VAR, str(chosen))
    resolved = resolve_target_root_for_cli(None)
    assert resolved == chosen.resolve()


def test_resolve_target_root_for_cli_refuses_linked_worktree_without_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside a linked worktree, no implicit fallback."""
    monkeypatch.delenv(RENDER_TARGET_ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_workspace._is_inside_linked_worktree",
        lambda *_a, **_kw: True,
    )
    with pytest.raises(RuntimeError, match="linked worktree"):
        resolve_target_root_for_cli(None)


def test_resolve_target_root_for_cli_falls_back_to_repo_root_outside_linked_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv(RENDER_TARGET_ROOT_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_workspace._is_inside_linked_worktree",
        lambda *_a, **_kw: False,
    )
    fallback_root = tmp_path / "repo-root"
    fallback_root.mkdir()
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_workspace._repo_root",
        lambda: fallback_root,
    )
    resolved = resolve_target_root_for_cli(None)
    assert resolved == fallback_root.resolve()
