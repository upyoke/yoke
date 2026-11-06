# ruff: noqa: E402, F401, F811 -- imported pytest fixtures are intentionally re-exported.
"""Shared setup for tests in this directory."""

from __future__ import annotations

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

LANE = "YOK-7777"


def _claim(real_db, *paths: str) -> None:
    with closing(connect_test_db(real_db)) as conn:
        actor = local_human(conn)
        target_ids = [seed_target(conn, path_string=path) for path in paths]
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=target_ids,
            item_id=7777,
        )
        conn.commit()


def _main_gains(project_repo, name: str) -> None:
    """Someone else's work lands on main."""
    (project_repo / name).write_text("someone else's landing\n")
    _git(project_repo, "add", name)
    _git(project_repo, "commit", "-q", "-m", f"main gains {name}")


def _record_receipt(real_db, *, commit_sha: str, touched=None) -> None:
    """The merge boundary's pre-landing receipt write."""
    with closing(connect_test_db(real_db)) as conn:
        record_entry(
            conn,
            item_id=7777,
            branch=LANE,
            target="main",
            commit_sha=commit_sha,
            touched_files=touched or (),
        )
        conn.commit()


def _record_landing(real_db, *, merge_sha: str, candidate: str, route: str) -> None:
    with closing(connect_test_db(real_db)) as conn:
        append_landing(
            conn,
            ItemLanding(
                item_id=7777,
                merge_sha=merge_sha,
                candidate_sha=candidate,
                pr_number="1" if route == "merge_queue" else "",
                target_branch="main",
                route=route,
                landed_at="2026-10-10T14:57:49Z",
            ),
        )
        # The swept lane is re-registered with no path and no head.
        conn.execute(
            "UPDATE item_worktrees SET path = NULL, commit_sha = NULL "
            "WHERE item_id = 7777"
        )
        conn.commit()


def _land_by_merge(project_repo, real_db, *, receipt: bool = True) -> str:
    """Merge the lane into main with a merge commit, then move main on."""
    candidate = _git(project_repo / ".worktrees" / LANE, "rev-parse", "HEAD")
    if receipt:
        observed = merge_git.changed_files(str(project_repo), candidate, "main")
        _record_receipt(real_db, commit_sha=candidate, touched=observed)
    _git(project_repo, "merge", "-q", "--no-ff", LANE, "-m", f"land {LANE}")
    merge_sha = _git(project_repo, "rev-parse", "HEAD")
    _main_gains(project_repo, "later.txt")
    _record_landing(
        real_db, merge_sha=merge_sha, candidate=candidate, route="merge_queue"
    )
    return merge_sha
