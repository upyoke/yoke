# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import closing

import pytest

from runtime.api.domain._path_claims_test_helpers import (
    HOLDER_SESSION_ID,
    local_human,
    seed_target,
    seed_test_holder_for,
)

from runtime.api.domain.path_claims_gate_boundary_test_support import (
    _commit_in_worktree,
    _git,
    project_repo,
    real_db,
)

from runtime.api.fixtures.file_test_db import connect_test_db

from yoke_core.domain.path_claim_boundary_gate_proof import (
    BoundaryProofError,
    boundary_context,
    build_local_boundary_proof,
    record_boundary_proof,
)

from yoke_core.domain.path_claim_boundary_proof_validation import _remote_heads

from yoke_core.domain.project_github_auth import MissingCapability, MissingPermission

from yoke_core.domain.gate_satisfier_stamp import read_rungs

from yoke_core.domain.function_response_refs import public_result

from yoke_core.domain.item_ref_render import render_item_refs

from yoke_core.domain.path_claims import register

from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item


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
        context = public_result(
            boundary_context(conn, 7777), render_item_refs(conn, [7777])
        )
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
