"""Focused tests for ``yoke board rebuild`` print modes."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.board import rebuild as board_rebuild
from yoke_contracts.machine_config import reader as machine_config


@pytest.fixture(autouse=True)
def connected_roster(monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.board.rebuild_resolve.missing_project_context",
        lambda **_kw: (
            "project_required: pass --repo-root PATH. Accessible projects: mine."
        ),
    )


def _configured_project(
    checkout: Path, project_id: int
) -> machine_config.ConfiguredProject:
    return machine_config.ConfiguredProject(
        checkout=checkout,
        project_id=project_id,
        entry={"project_id": project_id},
    )


def test_resolve_board_project_from_registered_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "externalwebapp"
    nested = checkout / "src"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    assert board_rebuild.resolve_main_repo_root() == checkout.resolve()


def test_resolve_board_project_rejects_home_machine_yoke_with_multiple_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yoke").mkdir()
    externalwebapp = tmp_path / "externalwebapp"
    yoke = tmp_path / "yoke"
    externalwebapp.mkdir()
    yoke.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [
            _configured_project(externalwebapp, 37),
            _configured_project(yoke, 1),
        ],
    )

    with pytest.raises(
        board_rebuild.BoardProjectResolutionError, match="project_required"
    ):
        board_rebuild.resolve_main_repo_root()


def test_resolve_board_project_falls_back_to_cwd_when_env_is_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "externalwebapp"
    nested = checkout / "src"
    home.mkdir()
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(home))
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    assert board_rebuild.resolve_main_repo_root() == checkout.resolve()


def test_resolve_board_project_refuses_single_registered_project_from_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "externalwebapp"
    home.mkdir()
    checkout.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    with pytest.raises(
        board_rebuild.BoardProjectResolutionError, match="project_required"
    ):
        board_rebuild.resolve_main_repo_root()


def test_resolve_board_project_rejects_unregistered_explicit_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "externalwebapp"
    other = tmp_path / "other"
    checkout.mkdir()
    other.mkdir()
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    with pytest.raises(board_rebuild.BoardProjectResolutionError, match="not inside"):
        board_rebuild.resolve_main_repo_root(str(other))


def test_board_rebuild_fails_cleanly_when_project_is_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "home"
    externalwebapp = tmp_path / "externalwebapp"
    yoke = tmp_path / "yoke"
    outside.mkdir()
    externalwebapp.mkdir()
    yoke.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [
            _configured_project(externalwebapp, 37),
            _configured_project(yoke, 1),
        ],
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = cli_main(["board", "rebuild", "--print"])

    assert rc == 2
    assert stdout.getvalue() == ""
    assert "project_required" in stderr.getvalue()
    assert "Accessible projects: mine" in stderr.getvalue()
    assert str(externalwebapp) not in stderr.getvalue()
