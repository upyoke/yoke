"""Rehearsal refuses evidence for a lane-divergent numbered history."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401
    _seed_apply_item,
    apply_env,
)
from runtime.api.fixtures.migration_model_test import TEST_MIGRATION_MODULES_DIR
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401
from yoke_core.domain.coordination_leases import active_lease
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.migration_apply_contract import LEASE_KEY_PREFIX
from yoke_core.domain.migration_apply_rehearse import rehearse
from yoke_core.domain.migration_history import HistoryError


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _initialize_lane(apply_env: dict, *, replacement: bool = False) -> str:
    repo = Path(apply_env["worktree"])
    modules = repo / TEST_MIGRATION_MODULES_DIR
    body = (modules / "sample_migration.py").read_text(encoding="utf-8")
    (modules / "0001_existing.py").write_text(body, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed history")
    _git(repo, "checkout", "-q", "-b", "lane")
    if replacement:
        (modules / "0001_existing.py").unlink()
        identifier = "0001_replacement"
    else:
        identifier = "0002_next"
    (modules / f"{identifier}.py").write_text(body, encoding="utf-8")
    return identifier


def test_rehearsal_accepts_history_that_extends_main(apply_env) -> None:
    identifier = _initialize_lane(apply_env)
    _seed_apply_item(
        apply_env["control_db"], item_id=6101, modules=[identifier]
    )

    result = rehearse(
        6101,
        session_id="session-history",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )

    assert result.all_succeeded


def test_rehearsal_refuses_divergent_history_before_taking_lease(apply_env) -> None:
    identifier = _initialize_lane(apply_env, replacement=True)
    _seed_apply_item(
        apply_env["control_db"], item_id=6102, modules=[identifier]
    )

    with pytest.raises(HistoryError, match="does not extend main"):
        rehearse(
            6102,
            session_id="session-history",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"],
        )

    conn = connect(apply_env["control_db"])
    try:
        assert active_lease(
            conn, "yoke", f"{LEASE_KEY_PREFIX}primary"
        ) is None
    finally:
        conn.close()
