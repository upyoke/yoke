# ruff: noqa: F401, F811 -- imported fixtures are intentionally re-exported.
"""Landing ends coverage enforcement; fresh rework still checks the lane."""

from contextlib import closing

from runtime.api.domain.path_claims_landed_boundary_test_support import (
    LANE, _claim, _land_by_merge, _commit_in_worktree, _git, project_repo, real_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item


def _gate(real_db, target_status="release"):
    return check_boundary_for_item(
        item_id=7777, target_status=target_status, db_path=real_db,
    )


def test_landed_item_closes_without_coverage_or_receipt(project_repo, real_db, monkeypatch):
    from yoke_core.domain import path_claims_gate_boundary as gate

    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="uncovered.py")
    _land_by_merge(project_repo, real_db, receipt=False)

    def no_claim_read(*_args):
        raise AssertionError("landed close-out must not recheck released coverage")

    monkeypatch.setattr(gate, "claims_for_boundary", no_claim_read)
    assert _gate(real_db) is None


def test_unlanded_rework_is_checked_from_the_lane(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _land_by_merge(project_repo, real_db)
    with closing(connect_test_db(real_db)) as conn:
        conn.execute(
            "UPDATE item_worktrees SET path = %s, commit_sha = %s WHERE item_id = 7777",
            (str(project_repo / ".worktrees" / LANE), "f" * 40),
        )
        conn.commit()
    _git(project_repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _commit_in_worktree(project_repo, name="bar.py")

    result = _gate(real_db, "reviewed-implementation")
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "offending paths: src/bar.py" in result["error"]
