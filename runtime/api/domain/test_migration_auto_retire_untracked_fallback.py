"""Untracked-file fallback path for auto-retire.

Lives in a sibling test module rather than test_migration_auto_retire.py
because the parent file is already near the project's 350-line per-file
limit. The fallback covers field-note 8728's observation that an
uncommitted module file at live-apply time recorded SKIP_NOT_TRACKED
and left the file in the working tree.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.migration_audit_schema import (
    ensure_migration_audit_table_postgres,
)
from yoke_core.domain.migration_auto_retire import (
    REMOVED_UNTRACKED,
    auto_retire_after_live_apply,
)


@pytest.fixture
def audit_conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        ensure_migration_audit_table_postgres(conn)
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def _record_audit(conn, *, name: str, model: str, state: str) -> None:
    conn.execute(
        "INSERT INTO migration_audit "
        "(migration_name, model_name, state, tables_declared, "
        "expected_deltas, pre_row_counts, backup_path, started_at) "
        "VALUES (%s, %s, %s, '[]', '{}', '{}', '', '2026-04-30T00:00:00Z')",
        (name, model, state),
    )
    conn.commit()


def _init_repo_with_baseline(repo: Path) -> Path:
    migrations = repo / "runtime" / "api" / "domain" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "__init__.py").write_text("")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "test"], check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True,
    )
    return migrations


def test_auto_retire_removes_untracked_module_via_unlink_fallback(
    audit_conn, tmp_path: Path,
):
    """A module file written by the slice but not yet committed at
    live-apply time is `git rm`-untrackable. Pre-fix the helper recorded
    SKIP_NOT_TRACKED ("module_file_not_in_git") and left the file in
    the working tree, forcing the operator to manually rm. The fallback
    now plain-unlinks the untracked file and reports outcome=removed
    with reason=removed_untracked_via_unlink.
    """
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "repo_untracked"
    migrations = _init_repo_with_baseline(repo)
    # Write the module AFTER the init commit and do NOT git-add it.
    untracked = migrations / "uncommitted_module.py"
    untracked.write_text("def apply(c): pass\n")
    assert untracked.exists()

    _record_audit(
        audit_conn, name="uncommitted_module", model="primary",
        state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model={
            "runner": {
                "config": {"modules_dir": "runtime/api/domain/migrations"},
            },
            "authoritative_db": {
                "kind": "sqlite_file",
                "location": {"path": "data/yoke.db"},
            },
        },
        profile={
            "model_name": "primary",
            "migration_modules": ["uncommitted_module"],
        },
        worktree_path=repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    outcomes = payload.get("outcomes") or []
    module_path = "runtime/api/domain/migrations/uncommitted_module.py"
    module_outcome = next(
        (o for o in outcomes if o["path"] == module_path), None,
    )
    assert module_outcome is not None
    assert module_outcome["outcome"] == "removed"
    assert module_outcome.get("reason") == REMOVED_UNTRACKED
    assert not untracked.exists()
