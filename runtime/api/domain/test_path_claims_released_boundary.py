# ruff: noqa: F401, F811
"""Releasing landed claims preserves enforcement of the merge boundary."""

from contextlib import closing

from runtime.api.domain.path_claims_landed_boundary_test_support import (
    _claim,
    _land_by_merge,
    _commit_in_worktree,
    project_repo,
    real_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.path_claims_gate_boundary import (
    check_boundary_for_item,
    claims_for_boundary,
)
from yoke_core.domain.path_claims_landing import release_landed_claims


def test_released_coverage_still_rejects_undeclared_landed_files(project_repo, real_db):
    _claim(real_db, "covered.py")
    _commit_in_worktree(project_repo, name="undeclared.py")
    _land_by_merge(project_repo, real_db)
    with closing(connect_test_db(real_db)) as connection:
        released = release_landed_claims(connection, item_id=7777)
        connection.commit()
        assert released
        assert [
            claim_id for claim_id, _ in claims_for_boundary(connection, 7777)
        ] == released
    verdict = check_boundary_for_item(
        item_id=7777, target_status="release", db_path=real_db
    )
    assert verdict["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "undeclared.py" in verdict["error"]
