"""Integration-lane landing records release both kinds of item-owned claims."""

# ruff: noqa: F811 -- imported fixtures are shared intentionally.
from contextlib import contextmanager
from subprocess import run
from types import SimpleNamespace

import pytest

from runtime.api.test_backlog import tmp_db, _conn  # noqa: F401
from runtime.api.domain.migration_apply_test_helpers import _seed_apply_item
from runtime.api.domain._path_claims_test_helpers import seed_target, seed_claim
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import item_landings_ops
from yoke_core.domain.item_landings import landings_for_item
from yoke_core.domain.item_landings_schema import ensure_item_landings_schema
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain import migration_territory_claim
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines import merge_worktree_landing as landing
from yoke_core.engines.merge_worktree_context import MergeArgs, MergeContext


def _git(root, *args):
    return run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.parametrize("local", [False, True])
def test_integration_landing_releases_path_and_migration_claims(
    tmp_db, tmp_path, monkeypatch, local
):
    item_id = 6101
    _seed_apply_item(tmp_db, item_id=item_id)
    conn = _conn(tmp_db)
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    workflow_id, version_id = resolve_current_workflow_pin(conn, "epic")
    conn.execute(
        "UPDATE items SET workflow_id=%s, workflow_version_id=%s WHERE id=%s",
        (workflow_id, version_id, item_id),
    )
    ensure_item_landings_schema(conn)
    path_claim = seed_claim(
        conn,
        item_id=item_id,
        target_id=seed_target(conn, path_string="src/widget.py"),
        state="active",
    )
    from runtime.api.fixtures.dispatch_actor import register_session_actor

    register_session_actor(conn, "session-a")
    territory = migration_territory_claim.enter(
        conn, project=1, model_name="primary", item_id=item_id, session_id="session-a"
    )
    conn.commit()

    @contextmanager
    def connected():
        yield conn

    monkeypatch.setattr(item_landings_ops, "_connect_rw", connected)
    monkeypatch.setattr(
        "yoke_core.domain.item_landings_close_out.public_item_target",
        lambda _: TargetRef(kind="item", item_id=item_id),
    )

    def dispatch(*, function_id, target, payload):
        assert function_id == "item_landings.record"
        result = item_landings_ops.handle_record_item_landing(
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(session_id="session-a"),
                target=target,
                payload=payload,
            )
        )
        return SimpleNamespace(success=result.primary_success, error=result.error)

    monkeypatch.setattr(
        "yoke_core.domain.item_landings_close_out.call_dispatcher", dispatch
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-b", "integration")
    _git(repo, "commit", "--allow-empty", "-m", "work")
    candidate = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "main")
    ctx = MergeContext(
        args=MergeArgs(branch="integration", local_merge=local, keep_remote=True),
        repo_root=str(repo),
        worktree_path=str(repo),
        epic_id=item_id,
    )
    monkeypatch.setattr(mw, "_schema_refresh", lambda *_: None)
    monkeypatch.setattr(mw, "_ensure_target_branch", lambda *_: None)
    monkeypatch.setattr(mw, "_sync_local_target", lambda *_: True)
    monkeypatch.setattr(
        "yoke_core.engines.merge_worktree_post_local._ensure_snapshot_for_project",
        lambda *_: None,
    )
    if local:
        assert mw.do_local_merge(ctx) == 0
        merge_sha = candidate
    else:
        _git(repo, "merge", "--no-ff", "--no-edit", "integration")
        merge_sha = _git(repo, "rev-parse", "HEAD")
        # A target advancing after landing must not become this item's identity.
        _git(repo, "commit", "--allow-empty", "-m", "neighbor")
        tip = _git(repo, "rev-parse", "HEAD")
        monkeypatch.setattr(
            "yoke_core.domain.merge_landing_proof.verified_target_sha", lambda *_: tip
        )
        assert mw._post_merge_cleanup(ctx, no_changes=False, pr_num="123") == 0
    rows = landings_for_item(conn, item_id)
    assert len(rows) == 1 and rows[0].merge_sha == merge_sha
    assert rows[0].candidate_sha == candidate
    assert conn.execute(
        "SELECT state, release_reason FROM path_claims WHERE id=%s", (path_claim,)
    ).fetchone()[:] == ("released", "landed")
    assert get_claim(conn, territory.id).released_at is not None
    assert landing.record_worktree_landing(
        ctx, candidate_sha=candidate, target_sha=merge_sha
    )
    assert len(landings_for_item(conn, item_id)) == 1
    conn.close()


def test_record_failure_preserves_retry_lane(monkeypatch):
    ctx = MergeContext(args=MergeArgs(branch="integration"), item_id=1, epic_id=1)
    monkeypatch.setattr(landing, "landing_merge_commit", lambda *a: "m" * 40)
    monkeypatch.setattr(
        landing, "close_out_lane", lambda **kw: (None, "control plane unavailable")
    )
    printed = []
    monkeypatch.setattr(mw, "_print", lambda text, **kw: printed.append(text))
    assert not landing.record_worktree_landing(
        ctx, candidate_sha="a" * 40, target_sha="m" * 40
    )
    assert "item_landing_record_failed" in printed[0] and "retry" in printed[0]


def test_failed_record_stops_before_cleanup(monkeypatch):
    from subprocess import CompletedProcess

    ctx = MergeContext(args=MergeArgs(branch="integration"), epic_id=1)
    calls = []

    def git(cmd, **kw):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, "a" * 40, "")

    monkeypatch.setattr(mw, "_run_git", git)
    monkeypatch.setattr(mw, "_emit_merge_event", lambda *a, **kw: None)
    monkeypatch.setattr(
        "yoke_core.domain.merge_landing_proof.verified_target_sha", lambda *a: "b" * 40
    )
    monkeypatch.setattr(landing, "landing_merge_commit", lambda *a: "b" * 40)
    monkeypatch.setattr(landing, "close_out_lane", lambda **kw: (None, "unavailable"))
    assert mw._post_merge_cleanup(ctx, no_changes=False) == 5
    assert calls == [["rev-parse", "integration"]]


def test_retry_refuses_local_only_ancestry_in_pr_mode(monkeypatch):
    from unittest.mock import Mock
    from yoke_core.domain.merge_landing_proof import LandingUnverified

    ctx = MergeContext(args=MergeArgs(branch="integration"), epic_id=1)
    record = Mock()
    monkeypatch.setattr(landing, "record_worktree_landing", record)
    proof = Mock(
        side_effect=LandingUnverified("merge_candidate_not_landed: publish and retry")
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_landing_proof.verified_target_sha", proof
    )
    assert landing.record_existing_landing(ctx, "a" * 40, "main") == 1
    proof.assert_called_once_with(ctx.repo_root, "main", "a" * 40)
    record.assert_not_called()
