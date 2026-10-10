# ruff: noqa: F401, F811 -- imported pytest fixtures are intentionally re-exported.
"""The boundary gate proves a landed item from its merge, not the moving head.

A recorded landing fixes what the item put on its target: the merge's diff
against its first parent. These cases land a path-claimed item, move the
target on past it, and ask the gate again with no lane, the way a hosted
control plane does at close-out.
"""

from __future__ import annotations

import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from runtime.api.domain._path_claims_test_helpers import local_human, seed_target
from runtime.api.domain.test_path_claim_boundary_gate_proof import (
    _record,
    _seed_proof_case,
)
from runtime.api.domain.test_path_claims_gate_boundary import (
    _commit_in_worktree,
    _git,
    project_repo,
    real_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import path_claims_landed_boundary as landed
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.item_landings import ItemLanding, append_landing
from yoke_core.domain.path_claim_boundary_gate_proof import BoundaryProofError
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item
from yoke_core.domain.project_github_auth import MissingCapability


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


def _land_and_move_main(project_repo, real_db, *, lane_head: str = "") -> str:
    """Merge the lane into main, advance main past it, retire the lane."""
    candidate = _git(project_repo / ".worktrees" / "YOK-7777", "rev-parse", "HEAD")
    _git(project_repo, "merge", "-q", "--no-ff", "YOK-7777", "-m", "land YOK-7777")
    merge_sha = _git(project_repo, "rev-parse", "HEAD")
    (project_repo / "later.txt").write_text("someone else's landing\n")
    _git(project_repo, "add", "later.txt")
    _git(project_repo, "commit", "-q", "-m", "main moves on")
    _git(project_repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    with closing(connect_test_db(real_db)) as conn:
        append_landing(
            conn,
            ItemLanding(
                item_id=7777,
                merge_sha=merge_sha,
                candidate_sha=candidate,
                pr_number="1",
                target_branch="main",
                route="merge_queue",
                landed_at="2026-10-10T14:57:49Z",
            ),
        )
        # The swept lane is re-registered with no path and no head.
        conn.execute(
            "UPDATE item_worktrees SET path = NULL, commit_sha = %s "
            "WHERE item_id = 7777",
            (lane_head or None,),
        )
        conn.commit()
    return merge_sha


def _fake_github(project_repo, monkeypatch, *, files=None) -> list:
    calls: list = []

    def _rest_get(path, *, token, query=None):
        calls.append(path)
        sha = path.rsplit("/", 1)[-1]
        if "/commits/" in path:
            parent = _git(project_repo, "rev-parse", f"{sha}^1")
            return {"sha": sha, "parents": [{"sha": parent}]}
        base, head = sha.split("...")
        if files is not None:
            return {"files": files}
        names = _git(project_repo, "diff", "--name-only", f"{base}..{head}")
        return {
            "files": [
                {"filename": name, "status": "modified"} for name in names.splitlines()
            ]
        }

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda *_a, **_k: SimpleNamespace(repo="test/test", token="t"),
    )
    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", _rest_get)
    monkeypatch.setattr(landed, "_local_checkouts", lambda *_a: [])
    return calls


def _gate(real_db, target_status: str = "release"):
    return check_boundary_for_item(
        item_id=7777, target_status=target_status, db_path=real_db
    )


def test_hosted_close_out_proves_landed_item_after_main_moved(
    project_repo, real_db, monkeypatch
):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    merge_sha = _land_and_move_main(project_repo, real_db)
    calls = _fake_github(project_repo, monkeypatch)

    assert _gate(real_db) is None
    assert any("/compare/" in call and merge_sha in call for call in calls)
    with closing(connect_test_db(real_db)) as conn:
        stamp = read_rungs(conn, 7777)[0]
    assert stamp["rung_id"] == landed.LANDED_MERGE_RUNG
    fact = json.loads(stamp["facts"]["observed:landed_merge"])
    assert fact["merge_sha"] == merge_sha
    assert fact["source"] == "github"
    assert fact["touched_paths"] == ["src/foo.py"]


def test_landed_file_outside_coverage_is_named(project_repo, real_db, monkeypatch):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _commit_in_worktree(project_repo, name="bar.py")
    _land_and_move_main(project_repo, real_db)
    _fake_github(project_repo, monkeypatch)

    result = _gate(real_db)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "src/bar.py" in result["error"]
    assert "claims path widen" in result["error"]


def test_local_checkout_holding_the_merge_answers_from_git(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _land_and_move_main(project_repo, real_db)

    assert _gate(real_db) is None
    with closing(connect_test_db(real_db)) as conn:
        fact = json.loads(read_rungs(conn, 7777)[0]["facts"]["observed:landed_merge"])
    assert fact["source"] == "git"


def test_unlanded_rework_is_checked_from_the_lane(project_repo, real_db):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _land_and_move_main(project_repo, real_db, lane_head="f" * 40)
    with closing(connect_test_db(real_db)) as conn:
        conn.execute(
            "UPDATE item_worktrees SET path = %s WHERE item_id = 7777",
            (str(project_repo / ".worktrees" / "YOK-7777"),),
        )
        conn.commit()
    _commit_in_worktree(project_repo, name="bar.py")

    result = _gate(real_db, "reviewed-implementation")
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "offending paths: src/bar.py" in result["error"]


def test_no_checkout_and_no_github_is_a_named_refusal(
    project_repo, real_db, monkeypatch
):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    merge_sha = _land_and_move_main(project_repo, real_db)

    def _missing(*_a, **_k):
        raise MissingCapability("yoke", "no GitHub capability")

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth", _missing
    )
    monkeypatch.setattr(landed, "_local_checkouts", lambda *_a: [])

    result = _gate(real_db)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert merge_sha in result["error"]
    assert "fetch the integration target" in result["error"]
    assert "re-run the same close-out" in result["error"]


def test_github_file_list_cap_refuses_instead_of_passing(
    project_repo, real_db, monkeypatch
):
    _claim(real_db, "src/foo.py")
    _commit_in_worktree(project_repo, name="foo.py")
    _land_and_move_main(project_repo, real_db)
    capped = [{"filename": "src/foo.py", "status": "modified"}] * (
        landed.GITHUB_COMPARE_FILE_LIMIT
    )
    _fake_github(project_repo, monkeypatch, files=capped)

    result = _gate(real_db)
    assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
    assert "300-file" in result["error"]


def test_caller_proof_cannot_claim_the_landed_rung(project_repo, real_db):
    _claim_id, _lane, _context, proof = _seed_proof_case(project_repo, real_db)
    proof["rung_id"] = landed.LANDED_MERGE_RUNG

    with pytest.raises(BoundaryProofError, match="unsupported rung"):
        _record(real_db, proof)
