"""Tests for the auto-retire helper."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import migration_auto_retire
from yoke_core.domain.migration_audit_schema import (
    ensure_migration_audit_table_postgres,
)
from yoke_core.domain.migration_auto_retire import (
    SKIP_INCOMPLETE,
    SKIP_MULTI_INSTALL,
    _candidate_targets,
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


@pytest.fixture
def fake_repo(tmp_path: Path):
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "repo"
    (repo / "runtime" / "api" / "domain" / "migrations").mkdir(parents=True)
    (repo / "runtime" / "api" / "domain" / "migrations" / "__init__.py").write_text("")
    (repo / "runtime" / "api" / "domain" / "migrations" / "demo_module.py").write_text(
        "def apply(conn): pass\n"
    )
    (repo / "runtime" / "api" / "domain" / "test_demo_module.py").write_text(
        "def test_demo(): assert True\n"
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    return repo


def _single_install_model() -> Dict[str, Any]:
    return {
        "runner": {"config": {"modules_dir": "runtime/api/domain/migrations"}},
        "authoritative_db": {
            "kind": "postgres",
            "location": {"database_name": "alpha_primary"},
        },
    }


def _multi_install_model() -> Dict[str, Any]:
    return {
        "runner": {"config": {"modules_dir": "runtime/api/domain/migrations"}},
        "authoritative_db": {
            "installs": [
                {"database_name": "alpha_a"},
                {"database_name": "alpha_b"},
            ],
        },
    }


def test_auto_retire_stages_git_rm_for_single_install(audit_conn, fake_repo):
    _record_audit(
        audit_conn, name="demo_module", model="primary", state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model=_single_install_model(),
        profile={
            "model_name": "primary",
            "migration_modules": ["demo_module"],
        },
        worktree_path=fake_repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    assert payload.get("staged_for_commit") is True
    proc = subprocess.run(
        ["git", "-C", str(fake_repo), "status", "--short"],
        capture_output=True, text=True, check=True,
    )
    out = proc.stdout
    assert "D  runtime/api/domain/migrations/demo_module.py" in out
    assert "D  runtime/api/domain/test_demo_module.py" in out


def test_auto_retire_skips_multi_install(audit_conn, fake_repo):
    _record_audit(
        audit_conn, name="demo_module", model="primary", state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model=_multi_install_model(),
        profile={
            "model_name": "primary",
            "migration_modules": ["demo_module"],
        },
        worktree_path=fake_repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    assert payload.get("skipped") == SKIP_MULTI_INSTALL
    # Module file should still be present
    assert (fake_repo / "runtime/api/domain/migrations/demo_module.py").exists()


def test_auto_retire_skips_when_modules_not_all_completed(audit_conn, fake_repo):
    _record_audit(
        audit_conn, name="demo_module", model="primary", state="rehearsed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model=_single_install_model(),
        profile={
            "model_name": "primary",
            "migration_modules": ["demo_module"],
        },
        worktree_path=fake_repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    assert payload.get("skipped") == SKIP_INCOMPLETE
    assert (fake_repo / "runtime/api/domain/migrations/demo_module.py").exists()


def test_auto_retire_records_no_op_when_files_already_gone(
    audit_conn, fake_repo,
):
    _record_audit(
        audit_conn, name="ghost_module", model="primary", state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model=_single_install_model(),
        profile={
            "model_name": "primary",
            "migration_modules": ["ghost_module"],
        },
        worktree_path=fake_repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    assert payload.get("staged_for_commit") is False
    outcomes = payload.get("outcomes") or []
    assert outcomes
    assert all(o["outcome"] == "skipped" for o in outcomes)


def test_auto_retire_stages_test_alongside_module(audit_conn, tmp_path: Path):
    """Tickets that place tests alongside the module (recent governed-drop
    convention) MUST get those tests staged for retire too — not only the
    legacy one-level-up convention.
    """
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "repo_alongside"
    migrations = repo / "runtime" / "api" / "domain" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "__init__.py").write_text("")
    (migrations / "alongside_module.py").write_text("def apply(conn): pass\n")
    (migrations / "test_alongside_module.py").write_text(
        "def test_alongside(): assert True\n"
    )
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

    _record_audit(
        audit_conn, name="alongside_module", model="primary", state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="alpha",
        model=_single_install_model(),
        profile={
            "model_name": "primary",
            "migration_modules": ["alongside_module"],
        },
        worktree_path=repo,
        modules_dir_rel=Path("runtime/api/domain/migrations"),
        item_id=42,
    )
    assert payload.get("staged_for_commit") is True
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--short"],
        capture_output=True, text=True, check=True,
    )
    out = proc.stdout
    assert "D  runtime/api/domain/migrations/alongside_module.py" in out
    assert "D  runtime/api/domain/migrations/test_alongside_module.py" in out


def test_candidate_targets_includes_declared_test_roots():
    """Buzz-shape: modules at app/db/migrations, tests at app/tests/.

    Neither the alongside nor the one-level-up candidate matches Buzz's
    test convention. The fix surfaces app/tests/ via the explicit
    test_roots_rel argument (sourced in production from
    project_structure.test_roots).
    """
    candidates = _candidate_targets(
        Path("app/db/migrations"),
        "006_add_wacky",
        test_roots_rel=[Path("app/tests"), Path("web/tests")],
    )
    rendered = {str(c) for c in candidates}
    assert "app/db/migrations/006_add_wacky.py" in rendered
    assert "app/db/migrations/test_006_add_wacky.py" in rendered
    assert "app/db/test_006_add_wacky.py" in rendered
    assert "app/tests/test_006_add_wacky.py" in rendered
    assert "web/tests/test_006_add_wacky.py" in rendered


def test_candidate_targets_deduplicates_overlapping_test_roots():
    """A declared test root that coincides with the parent-of-modules-dir
    candidate must not double-add the same path."""
    candidates = _candidate_targets(
        Path("runtime/api/domain/migrations"),
        "demo",
        test_roots_rel=[Path("runtime/api/domain")],
    )
    rendered = [str(c) for c in candidates]
    assert rendered.count("runtime/api/domain/test_demo.py") == 1


def test_auto_retire_stages_buzz_shape_test_under_declared_test_root(
    audit_conn, tmp_path: Path, monkeypatch,
):
    """End-to-end: a Buzz-shape project (modules at app/db/migrations,
    test at app/tests/test_<id>.py) retires both files. Pre-fix the test
    file was silently stranded because the candidate list only covered
    modules_dir, modules_dir/test_, and modules_dir.parent/test_.
    """
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "repo_buzz_shape"
    migrations = repo / "app" / "db" / "migrations"
    tests = repo / "app" / "tests"
    migrations.mkdir(parents=True)
    tests.mkdir(parents=True)
    (migrations / "__init__.py").write_text("")
    (migrations / "006_add_wacky.py").write_text("def apply(conn): pass\n")
    (tests / "test_006_add_wacky.py").write_text(
        "def test_wacky(): assert True\n"
    )
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

    monkeypatch.setattr(
        migration_auto_retire, "_declared_test_roots",
        lambda project: [Path("app/tests"), Path("web/tests")],
    )

    _record_audit(
        audit_conn, name="006_add_wacky", model="primary", state="completed",
    )
    payload = auto_retire_after_live_apply(
        audit_conn=audit_conn,
        project="buzz",
        model={
            "runner": {"config": {"modules_dir": "app/db/migrations"}},
            "authoritative_db": {
                "kind": "postgres",
                "location": {"database_name": "buzz_primary"},
            },
        },
        profile={
            "model_name": "primary",
            "migration_modules": ["006_add_wacky"],
        },
        worktree_path=repo,
        modules_dir_rel=Path("app/db/migrations"),
        item_id=1882,
    )
    assert payload.get("staged_for_commit") is True
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--short"],
        capture_output=True, text=True, check=True,
    )
    out = proc.stdout
    assert "D  app/db/migrations/006_add_wacky.py" in out
    assert "D  app/tests/test_006_add_wacky.py" in out
