"""Hosted path-claim boundary proof and freshness coverage."""

from __future__ import annotations

from contextlib import closing

import pytest

from runtime.api.domain._path_claims_test_helpers import (
    HOLDER_SESSION_ID,
    local_human,
    seed_target,
    seed_test_holder_for,
)
from runtime.api.domain.test_path_claims_gate_boundary import (
    _commit_in_worktree,
    _git,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.path_claim_boundary_gate_proof import (
    BoundaryProofError,
    boundary_context,
    build_local_boundary_proof,
    record_boundary_proof,
)
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item


pytest_plugins = ("runtime.api.domain.test_path_claims_gate_boundary",)


def _seed_proof_case(project_repo, real_db):
    with closing(connect_test_db(real_db)) as conn:
        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=7777,
        )
        seed_test_holder_for(conn, item_id=7777)
        conn.commit()
    _commit_in_worktree(project_repo, name="foo.py")
    lane = project_repo / ".worktrees" / "YOK-7777"
    head_sha = _git(lane, "rev-parse", "HEAD")
    base_sha = _git(project_repo, "rev-parse", "main")
    _git(project_repo, "update-ref", "refs/remotes/origin/main", base_sha)
    with closing(connect_test_db(real_db)) as conn:
        conn.execute(
            "UPDATE item_worktrees SET commit_sha = %s WHERE item_id = 7777",
            (head_sha,),
        )
        conn.commit()
        context = boundary_context(conn, 7777)
    proof = build_local_boundary_proof(context, str(lane))
    return claim_id, lane, context, proof


def _remote_from(proof):
    return {
        row["integration_target"]: row["integration_base_sha"]
        for row in proof["integration_bases"]
    }


def _record(real_db, proof):
    with closing(connect_test_db(real_db)) as conn:
        return record_boundary_proof(
            conn,
            item_id=7777,
            session_id=HOLDER_SESSION_ID,
            proof=proof,
        )


def _hosted_gate(real_db, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.path_claims_gate_boundary._resolve_repo_path",
        lambda *_args: None,
    )
    return check_boundary_for_item(
        item_id=7777,
        target_status="reviewed-implementation",
        db_path=real_db,
    )


def test_valid_remote_proof_passes_checkoutless_gate(
    project_repo,
    real_db,
    monkeypatch,
):
    _claim_id, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: _remote_from(proof),
    )
    _record(real_db, proof)
    assert _hosted_gate(real_db, monkeypatch) is None


def test_missing_proof_refuses_with_producer_command(
    project_repo,
    real_db,
    monkeypatch,
):
    _seed_proof_case(project_repo, real_db)
    result = _hosted_gate(real_db, monkeypatch)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "claims path boundary-prove --item YOK-7777" in result["error"]


@pytest.mark.parametrize("stale_fact", ["coverage", "head", "base"])
def test_changed_authoritative_fact_refuses_old_proof(
    project_repo,
    real_db,
    monkeypatch,
    stale_fact,
):
    claim_id, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    remote = _remote_from(proof)
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: remote,
    )
    _record(real_db, proof)
    with closing(connect_test_db(real_db)) as conn:
        if stale_fact == "coverage":
            extra = seed_target(conn, path_string="src/extra.py")
            conn.execute(
                "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
                "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
                (claim_id, extra),
            )
        elif stale_fact == "head":
            conn.execute(
                "UPDATE item_worktrees SET commit_sha = %s WHERE item_id = 7777",
                ("f" * 40,),
            )
        conn.commit()
    if stale_fact == "base":
        remote["main"] = "e" * 40
    result = _hosted_gate(real_db, monkeypatch)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "boundary-prove" in result["error"]


def test_incomplete_check_is_named_refusal_not_attribute_error(
    project_repo,
    real_db,
    monkeypatch,
):
    _claim_id, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    proof["checks"] = [{"integration_target": "main"}]
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: _remote_from(proof),
    )
    with pytest.raises(BoundaryProofError, match="incomplete check result"):
        _record(real_db, proof)


def test_local_integration_capability_does_not_require_github(
    project_repo,
    real_db,
    monkeypatch,
):
    _claim_id, _lane, context, _proof = _seed_proof_case(project_repo, real_db)
    _git(project_repo, "update-ref", "-d", "refs/remotes/origin/main")
    proof = build_local_boundary_proof(context, str(context["lane"]["path"]))
    assert proof["rung_id"] == "local_integration_ref"
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: pytest.fail("local proof must not require GitHub"),
    )
    _record(real_db, proof)
    assert _hosted_gate(real_db, monkeypatch) is None


def test_remote_tip_advance_needs_reproof_but_not_rebase(
    project_repo,
    real_db,
    monkeypatch,
):
    _claim_id, lane, context, first = _seed_proof_case(project_repo, real_db)
    original_merge_base = first["integration_bases"][0]["merge_base_sha"]
    (project_repo / "base.txt").write_text("advanced\n")
    _git(project_repo, "add", "base.txt")
    _git(project_repo, "commit", "-q", "-m", "advance main")
    new_tip = _git(project_repo, "rev-parse", "main")
    _git(project_repo, "update-ref", "refs/remotes/origin/main", new_tip)
    second = build_local_boundary_proof(context, str(lane))
    assert second["integration_bases"][0] == {
        "integration_target": "main",
        "integration_base_sha": new_tip,
        "merge_base_sha": original_merge_base,
    }
    monkeypatch.setattr(
        "yoke_core.domain.path_claim_boundary_proof_validation._remote_heads",
        lambda *_args: {"main": new_tip},
    )
    _record(real_db, second)


def test_direct_boundary_stamps_local_rung(project_repo, real_db):
    with closing(connect_test_db(real_db)) as conn:
        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=7777,
        )
    _commit_in_worktree(project_repo, name="foo.py")
    assert (
        check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        is None
    )
    with closing(connect_test_db(real_db)) as conn:
        stamp = read_rungs(conn, 7777)[0]
    assert stamp["rung_id"] == "local_integration_ref"
    assert stamp["target_status"] == "reviewed-implementation"


def test_direct_boundary_prefers_remote_rung(project_repo, real_db):
    with closing(connect_test_db(real_db)) as conn:
        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=7777,
        )
    _commit_in_worktree(project_repo, name="foo.py")
    _git(
        project_repo,
        "update-ref",
        "refs/remotes/origin/main",
        _git(project_repo, "rev-parse", "main"),
    )
    assert (
        check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        is None
    )
    with closing(connect_test_db(real_db)) as conn:
        assert read_rungs(conn, 7777)[0]["rung_id"] == "remote_integration_ref"
