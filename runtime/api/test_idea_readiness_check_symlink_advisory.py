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
from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT


def _budget_spec() -> str:
    return (
        "## File Budget\n\n- `CLAUDE.md` — current 1 lines; remaining "
        f"headroom {DEFAULT_LIMIT - 1}; at-or-over-limit: false; "
        "responsibility: edit rules.\n"
    )


@pytest.fixture
def symlink_repo(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("agents")
    os.symlink("AGENTS.md", tmp_path / "CLAUDE.md")
    return tmp_path


def test_collects_file_budget_symlink_advisory(symlink_repo: Path):
    spec = _budget_spec()
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
        "item_project_checkout",
        lambda conn, item_id: symlink_repo,
    )
    # Acceptance criteria are outside this focused path-advisory check.
    monkeypatch.setattr(
        idea_readiness_check,
        "verify_refine_acceptance_criteria",
        lambda conn, item_id, spec: [],
    )
    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(db_name)
    pg_testdb.drop_database_on_close(conn, db_name)
    from yoke_core.domain.workflow_schema import ensure_workflow_schema
    from yoke_core.domain.workflow_registry import converge_builtin_workflows

    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, status TEXT, "
        "workflow_id TEXT, workflow_version_id INTEGER, workflow_posture TEXT)"
    )
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    conn.execute(
        "CREATE TABLE path_claims ("
        "id INTEGER PRIMARY KEY, owner_kind TEXT, "
        "owner_item_id INTEGER, state TEXT)"
    )
    conn.execute(
        "CREATE TABLE path_targets ("
        "id INTEGER PRIMARY KEY, path_string TEXT, kind TEXT)"
    )
    conn.execute(
        "CREATE TABLE path_claim_targets (claim_id INTEGER, target_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO items (id, spec, status, workflow_id, workflow_version_id, "
        "workflow_posture) VALUES (1, %s, 'idea', 'dash', "
        "(SELECT current_version_id FROM workflows WHERE id='dash'), '{}')",
        (_budget_spec(),),
    )
    conn.execute(
        "INSERT INTO path_claims "
        "(id, owner_kind, owner_item_id, state) "
        "VALUES (10, 'item', 1, 'planned')"
    )
    conn.execute("INSERT INTO path_targets VALUES (1, 'CLAUDE.md', 'file')")
    conn.execute("INSERT INTO path_claim_targets VALUES (10, 1)")
    conn.commit()
    try:
        outcome = idea_readiness_check.run_all_checks(conn, 1)
        assert outcome.issues == []
        assert outcome.unavailable == []
        advisories = outcome.advisories
    finally:
        conn.close()
    assert [a["code"] for a in advisories] == [ADVISORY_CODE]
