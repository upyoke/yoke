# ruff: noqa: F401, F811 -- imported pytest fixtures are intentionally re-exported.
"""The boundary gate proves a landed item from its receipt, not the moving head.

A recorded landing fixes what the item put on its target: the files its
merge receipt recorded against the target as it stood before the landing.
These cases land a path-claimed item, move the target on past it, and ask
the gate again with no lane, the way a hosted control plane does at
close-out. The fast-forward case is the one a first-parent diff gets wrong.
"""

from __future__ import annotations

from runtime.api.domain.path_claims_landed_boundary_test_support import (
    LANE as LANE,
    _claim as _claim,
    _land_by_merge as _land_by_merge,
    _main_gains as _main_gains,
    _record_landing as _record_landing,
    _record_receipt as _record_receipt,
)


import json
from contextlib import closing

import pytest

from runtime.api.domain._path_claims_test_helpers import local_human, seed_target
from runtime.api.domain.path_claim_boundary_gate_proof_test_support import (
    _record,
    _seed_proof_case,
)
from runtime.api.domain.path_claims_gate_boundary_test_support import (
    _commit_in_worktree,
    _git,
    project_repo,
    real_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import path_claims_landed_boundary as landed
from yoke_core.domain import standalone_item_merge_git as merge_git
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.item_landings import ItemLanding, append_landing
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.path_claim_boundary_gate_proof import BoundaryProofError
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item


def _gate(real_db, target_status: str = "release"):
    return check_boundary_for_item(
        item_id=7777, target_status=target_status, db_path=real_db
    )


def _landed_fact(real_db) -> dict:
    with closing(connect_test_db(real_db)) as conn:
        stamp = read_rungs(conn, 7777)[0]
    assert stamp["rung_id"] == landed.LANDED_MERGE_RUNG
    return json.loads(stamp["facts"]["observed:landed_merge"])


def test_fast_forward_of_a_lane_that_merged_main_charges_only_its_own_files(
    project_repo, real_db
):
    worktree = project_repo / ".worktrees" / LANE
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _main_gains(project_repo, "synced.txt")
    _git(worktree, "merge", "-q", "--no-ff", "main", "-m", "sync main")
    tip = _git(worktree, "rev-parse", "HEAD")
    observed = merge_git.changed_files(str(project_repo), tip, "main")
    _record_receipt(real_db, commit_sha=tip, touched=observed)
    _git(project_repo, "merge", "-q", "--ff-only", LANE)
    first_parent_diff = _git(project_repo, "diff", "--name-only", f"{tip}^1", tip)
    assert "synced.txt" in first_parent_diff.splitlines()
    _main_gains(project_repo, "later.txt")
    _record_landing(real_db, merge_sha=tip, candidate=tip, route="fast_forward")

    assert _gate(real_db) is None
    fact = _landed_fact(real_db)
    assert fact["merge_sha"] == tip
    assert fact["source"] == "merge_receipt"
    assert fact["touched_paths"] == ["src/foo.py"]


def test_merge_commit_landing_proves_the_same_files(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    merge_sha = _land_by_merge(project_repo, real_db)

    assert _gate(real_db) is None
    fact = _landed_fact(real_db)
    assert fact["merge_sha"] == merge_sha
    assert fact["touched_paths"] == ["src/foo.py"]
    assert fact["receipt_branch"] == LANE


def test_landed_file_outside_coverage_is_named(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _commit_in_worktree(project_repo, name="bar.py")
    _land_by_merge(project_repo, real_db)

    result = _gate(real_db)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "src/bar.py" in result["error"]
    assert "claims path widen" in result["error"]


def test_landing_without_a_receipt_is_a_named_refusal(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    merge_sha = _land_by_merge(project_repo, real_db, receipt=False)

    result = _gate(real_db)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "landed_boundary_receipt_missing" in result["error"]
    assert merge_sha in result["error"]
    assert "yoke merge item YOK-7777" in result["error"]
    assert "yoke say --steering" in result["error"]


def test_receipt_for_another_candidate_does_not_prove_the_landing(
    project_repo, real_db
):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _record_receipt(real_db, commit_sha="e" * 40, touched=["src/foo.py"])
    _land_by_merge(project_repo, real_db, receipt=False)

    result = _gate(real_db)
    assert "landed_boundary_receipt_missing" in result["error"]


def test_receipt_without_changed_files_is_a_named_refusal(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    candidate = _git(project_repo / ".worktrees" / LANE, "rev-parse", "HEAD")
    _record_receipt(real_db, commit_sha=candidate)
    _land_by_merge(project_repo, real_db, receipt=False)

    result = _gate(real_db)
    assert "landed_boundary_receipt_files_missing" in result["error"]
    assert "re-records the receipt's changed files" in result["error"]


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


def test_caller_proof_cannot_claim_the_landed_rung(project_repo, real_db):
    _claim_id, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    proof["rung_id"] = landed.LANDED_MERGE_RUNG

    with pytest.raises(BoundaryProofError, match="unsupported rung"):
        _record(real_db, proof)
