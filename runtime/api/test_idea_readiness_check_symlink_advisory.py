"""Coverage for symlink File Budget readiness advisories."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain import idea_readiness_check
from yoke_core.domain.idea_readiness_symlink_advisory import (
    ADVISORY_CODE,
    collect_symlink_advisories,
)


@pytest.fixture
def symlink_repo(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("agents")
    os.symlink("AGENTS.md", tmp_path / "CLAUDE.md")
    return tmp_path


def test_collects_file_budget_symlink_advisory(symlink_repo: Path):
    spec = "## File Budget\n\n- `CLAUDE.md` — edit rules.\n"
    advisories = collect_symlink_advisories(spec, repo_root=symlink_repo)
    assert len(advisories) == 1
    advisory = advisories[0]
    assert advisory["code"] == ADVISORY_CODE
    assert "`CLAUDE.md` is a symlink to `AGENTS.md`" in advisory["message"]
    assert advisory["context"] == {
        "symlink_path": "CLAUDE.md",
        "canonical_path": "AGENTS.md",
    }


def test_readiness_check_reports_advisory_without_blocking(
    symlink_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        idea_readiness_check,
        "_resolve_repo_root_for_item",
        lambda conn, item_id: symlink_repo,
    )
    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(db_name)
    pg_testdb.drop_database_on_close(conn, db_name)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT)")
    conn.execute(
        "CREATE TABLE path_claims ("
        "id INTEGER PRIMARY KEY, item_id INTEGER, state TEXT)"
    )
    conn.execute(
        "CREATE TABLE path_targets ("
        "id INTEGER PRIMARY KEY, path_string TEXT, kind TEXT)"
    )
    conn.execute(
        "CREATE TABLE path_claim_targets (claim_id INTEGER, target_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO items (id, spec) VALUES (1, %s)",
        ("## File Budget\n\n- `CLAUDE.md` — edit rules.\n",),
    )
    conn.execute("INSERT INTO path_claims VALUES (10, 1, 'planned')")
    conn.execute("INSERT INTO path_targets VALUES (1, 'CLAUDE.md', 'file')")
    conn.execute("INSERT INTO path_claim_targets VALUES (10, 1)")
    conn.commit()
    try:
        assert idea_readiness_check.run_all_checks(conn, 1) == []
        advisories = idea_readiness_check.run_all_advisories(conn, 1)
    finally:
        conn.close()
    assert [a["code"] for a in advisories] == [ADVISORY_CODE]
