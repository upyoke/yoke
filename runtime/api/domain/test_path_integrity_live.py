"""Live-project path-integrity coverage.

The verifier must run successfully against every registered project
whose path substrate exists, with at least one non-``yoke`` project
covered. We build a non-``yoke`` repo and substrate from scratch via
the Phase 0/1 surfaces (CPR + scanner), then run the verifier and
assert it produces a non-skipped run.

The substrate-only invariant guarantee is enforced upstream by
:func:`yoke_core.domain.path_integrity.verify_project` — it never
shells out to git. This test exercises that path with substrate that
was itself built from a real git tree, proving the verifier completes
on real-world rows without itself reading git state.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_integrity_test_helpers import path_integrity_db
from yoke_core.domain import path_integrity
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_snapshots import build_head_snapshot
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def alt_project_repo(tmp_path: Path):
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    repo = tmp_path / "alt-repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("# main\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def live_db(tmp_path: Path, alt_project_repo: Path):
    with path_integrity_db(tmp_path) as conn:
        p = _p(conn)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, default_branch, public_item_prefix, "
            f"created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (
                3, "alt", "alt-project", "main", "ALT", iso8601_now(),
            ),
        )
        register_machine_checkout(tmp_path / "machine-config", alt_project_repo, 3)
        conn.commit()
        yield conn


def test_verifier_passes_against_live_non_yoke_substrate(live_db):
    snapshot_id = build_head_snapshot(live_db, "alt")
    assert snapshot_id > 0

    run_id = path_integrity.verify_project(live_db, "alt")
    p = _p(live_db)
    row = live_db.execute(
        "SELECT status, failure_count, skip_reason "
        f"FROM path_integrity_runs WHERE id={p}",
        (run_id,),
    ).fetchone()
    assert row[0] == path_integrity.STATUS_PASSED
    assert row[1] == 0
    assert row[2] is None


def test_verify_all_projects_covers_both_alt_and_skips_empty(
    live_db,
):
    # Add a second registered project with no substrate. AC-15 says it
    # produces a skip row, not a silent fallback.
    p = _p(live_db)
    live_db.execute(
        "INSERT INTO projects "
        "(id, slug, name, default_branch, public_item_prefix, "
        f"created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
        (
            4, "empty", "empty-project", "main", "EMP", iso8601_now(),
        ),
    )
    live_db.commit()
    build_head_snapshot(live_db, "alt")

    run_ids = path_integrity.verify_all_projects(live_db)
    statuses = [
        live_db.execute(
            "SELECT p.slug, r.status, r.skip_reason "
            "FROM path_integrity_runs r "
            "JOIN projects p ON p.id = r.project_id "
            f"WHERE r.id={p}",
            (rid,),
        ).fetchone()
        for rid in run_ids
    ]
    by_project = {row[0]: (row[1], row[2]) for row in statuses}
    assert by_project["alt"][0] == path_integrity.STATUS_PASSED
    assert by_project["empty"][0] == path_integrity.STATUS_SKIPPED
    assert by_project["empty"][1] == path_integrity.SKIP_NO_SUBSTRATE


def test_has_green_run_resolves_for_live_substrate(live_db):
    build_head_snapshot(live_db, "alt")
    path_integrity.verify_project(live_db, "alt")
    sha = live_db.execute(
        "SELECT s.commit_sha FROM path_snapshots s "
        "JOIN projects p ON p.id = s.project_id "
        "WHERE p.slug='alt'",
    ).fetchone()[0]
    assert path_integrity.has_green_run(live_db, "alt", sha)
