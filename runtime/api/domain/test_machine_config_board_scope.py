from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain import machine_config


def _write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "machine-config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_board_scope_without_project_config_defaults_to_all(
    tmp_path: Path, monkeypatch
) -> None:
    config = _write_config(
        tmp_path,
        {"schema_version": 1, "settings": {"merge_conflict_threshold": "1"}},
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.board_scope(repo_root) == "all"


def test_board_scope_defaults_to_checkout_project_id(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "projects": {
                str(repo_root.resolve()): {
                    "project_id": 2,
                }
            },
        },
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.project_id(repo_root) == 2
    assert machine_config.board_scope(repo_root) == "2"


def test_board_scope_can_use_numeric_project_when_slug_omitted(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "projects": {str(repo_root.resolve()): {"project_id": 2}},
        },
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.board_scope(repo_root) == "2"


def test_project_entry_matches_worktree_to_main_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    worktree = repo_root / ".worktrees" / "branch"
    worktree.mkdir(parents=True)
    config = _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "projects": {
                str(repo_root.resolve()): {
                    "project_id": 1,
                }
            },
        },
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.project_id(worktree) == 1


def test_machine_project_board_can_override_scope_and_render_path(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "projects": {
                str(repo_root.resolve()): {
                    "project_id": 1,
                    "board": {
                        "scope": "all",
                        "render_path": ".yoke/BOARD-ALL.md",
                    },
                }
            },
        },
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.board_scope(repo_root) == "all"
    assert machine_config.board_render_path(repo_root) == (
        repo_root / ".yoke" / "BOARD-ALL.md"
    )


def test_board_art_path_is_project_local_and_not_configurable(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config = _write_config(
        tmp_path,
        {
            "schema_version": 1,
            "projects": {
                str(repo_root.resolve()): {
                    "project_id": 1,
                    "board": {
                        "render_path": ".yoke/BOARD.md",
                        "scope": "all",
                    },
                }
            },
        },
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(config))

    assert machine_config.board_art_path(repo_root) == repo_root / ".yoke" / "board-art"


def test_config_path_relative_env_anchors_under_machine_home(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "machine-home"
    monkeypatch.setenv(machine_config.HOME_ENV, str(home))
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, "yoke-machine-config.json")

    resolved = machine_config.config_path()

    assert resolved.is_absolute()
    assert resolved == home / "yoke-machine-config.json"


def test_config_path_relative_env_does_not_resolve_into_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    # Reproduces the pollution bug: a relative YOKE_MACHINE_CONFIG_FILE must
    # anchor under the machine home, never the process cwd (a checkout/worktree
    # tree) — otherwise config writes land inside whatever checkout is active.
    home = tmp_path / "machine-home"
    checkout = tmp_path / "repo" / ".worktrees" / "branch"
    checkout.mkdir(parents=True)
    monkeypatch.setenv(machine_config.HOME_ENV, str(home))
    monkeypatch.setenv(
        machine_config.CONFIG_FILE_ENV, "machine-config/yoke-machine-config.json"
    )
    monkeypatch.chdir(checkout)

    resolved = machine_config.config_path()

    assert resolved.is_absolute()
    assert not resolved.is_relative_to(checkout)
    assert resolved == home / "machine-config" / "yoke-machine-config.json"


def test_config_path_absolute_env_is_returned_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    absolute = tmp_path / "explicit" / "config.json"
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(absolute))

    assert machine_config.config_path() == absolute


def test_cli_config_path_relative_env_anchors_under_machine_home(
    tmp_path: Path, monkeypatch
) -> None:
    from yoke_cli.config import machine_config as cli_machine_config

    home = tmp_path / "machine-home"
    monkeypatch.setenv(cli_machine_config.HOME_ENV, str(home))
    monkeypatch.setenv(cli_machine_config.CONFIG_FILE_ENV, "yoke-machine-config.json")

    resolved = cli_machine_config.config_path()

    assert resolved.is_absolute()
    assert resolved == home / "yoke-machine-config.json"


def test_register_machine_checkout_refuses_relative_config_root(
    tmp_path: Path,
) -> None:
    # The fixture writes yoke-machine-config.json directly (not through
    # config_path's anchoring), so a relative config_root would drop the file
    # into the process cwd — the exact machine-config pollution being closed.
    from runtime.api.fixtures.machine_config_test import register_machine_checkout

    with pytest.raises(ValueError, match="absolute config_root"):
        register_machine_checkout(Path("machine-config"), tmp_path / "repo", 1)


def test_register_machine_checkout_refuses_config_root_outside_temp(
    tmp_path: Path,
) -> None:
    # An absolute-but-source-tree config_root (e.g. a live checkout's
    # repo_root.parent) is the other pollution path: it lands the temp config in
    # the real .worktrees/. Only the OS temp dir is allowed.
    from runtime.api.fixtures.machine_config_test import register_machine_checkout

    with pytest.raises(ValueError, match="not under a temp root"):
        register_machine_checkout(
            Path("/opt/not-a-temp-dir/machine-config"), tmp_path / "repo", 1
        )


def test_clear_machine_checkout_unsets_leaked_env(tmp_path: Path) -> None:
    # register_ sets YOKE_MACHINE_CONFIG_FILE directly on os.environ; clear_
    # must unset it so the pointer does not leak into later tests/operations.
    from runtime.api.fixtures.machine_config_test import (
        clear_machine_checkout,
        register_machine_checkout,
    )

    register_machine_checkout(tmp_path / "machine-config", tmp_path / "repo", 7)
    assert os.environ.get("YOKE_MACHINE_CONFIG_FILE")

    clear_machine_checkout(7)
    assert "YOKE_MACHINE_CONFIG_FILE" not in os.environ
