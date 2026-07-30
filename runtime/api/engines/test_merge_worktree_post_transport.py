"""Transport-aware routing regression tests for the merge finalize path.

The finalize phase's control-plane touches must route through the
transport-aware ``call_dispatcher`` facade (or, for schema refresh, be
skipped over https) so the flow works over an https control plane, not
only a local Postgres connection. These tests monkeypatch
``call_dispatcher`` in each finalize module and assert every migrated touch
relays instead of opening a bare local ``mw._connect()`` — with the
snapshot pre-warm, post-rebase requirement, and schema-refresh behaviors
preserved. The prune verdict's routing + decisions are proven end-to-end in
``test_merge_worktree_safe_prune``.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines import merge_worktree_post_helpers as post_helpers
from yoke_core.engines import merge_worktree_post_local as post_local
from yoke_core.engines import merge_worktree_tests as mtests
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

_HTTPS_CHECK = (
    "yoke_core.domain.worktree_create_db.item_worktree_authority_is_https"
)


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _no_bare_db(monkeypatch):
    monkeypatch.setattr(
        mw, "_connect",
        lambda *_a, **_k: pytest.fail("must not open a bare mw._connect()"),
    )


# ---------------------------------------------------------------------------
# _ensure_snapshot_for_project — path-snapshot write relays
# ---------------------------------------------------------------------------
class TestSnapshotEnsureRelays:
    def test_resolves_head_locally_and_relays_ensure_at(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp("project.snapshot.ensure_at", {"snapshot_id": 5})

        monkeypatch.setattr(post_local, "call_dispatcher", fake)
        monkeypatch.setattr(
            subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="abc123\n"),
        )
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), repo_root="/repo")
        post_local._ensure_snapshot_for_project(ctx)

        assert len(calls) == 1
        assert calls[0]["function_id"] == "project.snapshot.ensure_at"
        assert calls[0]["target"].kind == "global"
        assert calls[0]["payload"]["commit_sha"] == "abc123"
        assert calls[0]["payload"]["project"] == "yoke"

    def test_no_head_skips_relay(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            post_local, "call_dispatcher",
            lambda **k: calls.append(k) or _resp("project.snapshot.ensure_at"),
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=1, stdout=""),
        )
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), repo_root="/repo")
        post_local._ensure_snapshot_for_project(ctx)
        assert calls == []

    def test_relay_failure_is_advisory(self, monkeypatch, capsys):
        monkeypatch.setattr(
            post_local, "call_dispatcher",
            lambda **k: _resp("project.snapshot.ensure_at", success=False),
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="abc123\n"),
        )
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), repo_root="/repo")
        # Advisory: a failed relay must not raise.
        post_local._ensure_snapshot_for_project(ctx)
        assert "ensure_snapshot_at advisory" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _post_rebase_requirement_id — materialize + read relays
# ---------------------------------------------------------------------------
class TestPostRebaseRelays:
    def test_relays_and_returns_requirement_id(self, monkeypatch):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(
                "merge.tests.post_rebase_requirement", {"requirement_id": 73}
            )

        monkeypatch.setattr(mtests, "call_dispatcher", fake)
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), item_id="42")
        assert mtests._post_rebase_requirement_id(ctx) == 73
        assert calls[0]["function_id"] == "merge.tests.post_rebase_requirement"
        assert calls[0]["target"].kind == "item"
        assert calls[0]["target"].item_id == 42
        assert calls[0]["payload"] == {"transition_id": "release"}

    def test_none_when_no_requirement(self, monkeypatch):
        monkeypatch.setattr(
            mtests, "call_dispatcher",
            lambda **k: _resp(
                "merge.tests.post_rebase_requirement", {"requirement_id": None}
            ),
        )
        _no_bare_db(monkeypatch)
        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), item_id="42")
        assert mtests._post_rebase_requirement_id(ctx) is None

    def test_unparseable_item_skips_relay(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            mtests, "call_dispatcher",
            lambda **k: called.append(k) or _resp("x"),
        )
        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), item_id=None)
        assert mtests._post_rebase_requirement_id(ctx) is None
        assert called == []

    def test_genuine_materialize_failure_raises(self, monkeypatch):
        # The handler's own domain error blocks the merge, exactly as the
        # pre-relay inline ``materialize_for_item`` call did.
        resp = FunctionCallResponse(
            success=False,
            function="merge.tests.post_rebase_requirement",
            version="v1",
            error=FunctionError(
                code="post_rebase_requirement_failed", message="plan has no cases"
            ),
        )
        monkeypatch.setattr(mtests, "call_dispatcher", lambda **k: resp)
        _no_bare_db(monkeypatch)
        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), item_id="42")
        with pytest.raises(RuntimeError, match="post-rebase QA materialization"):
            mtests._post_rebase_requirement_id(ctx)

    def test_infrastructure_failure_degrades_to_none(self, monkeypatch):
        # An unresolved session / unavailable relay must not block the merge;
        # it degrades to "no post-rebase QA case" like the prep gates.
        resp = FunctionCallResponse(
            success=False,
            function="merge.tests.post_rebase_requirement",
            version="v1",
            error=FunctionError(
                code="actor_session_missing", message="no ambient session"
            ),
        )
        monkeypatch.setattr(mtests, "call_dispatcher", lambda **k: resp)
        _no_bare_db(monkeypatch)
        ctx = MergeContext(args=MergeArgs(branch="YOK-42"), item_id="42")
        assert mtests._post_rebase_requirement_id(ctx) is None


# ---------------------------------------------------------------------------
# _schema_refresh — skip over https, converge locally
# ---------------------------------------------------------------------------
class TestSchemaRefreshTransport:
    def test_skips_over_https(self, monkeypatch, capsys):
        calls = []
        monkeypatch.setattr(
            mw, "_run_python_module", lambda *a, **k: calls.append(a)
        )
        monkeypatch.setattr(_HTTPS_CHECK, lambda: True)

        post_helpers._schema_refresh(SimpleNamespace())
        assert calls == []
        assert "Skipping schema refresh over https" in capsys.readouterr().out

    def test_converges_local_db_off_https(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            mw, "_run_python_module",
            lambda module, args, **k: calls.append((module, tuple(args))),
        )
        monkeypatch.setattr(_HTTPS_CHECK, lambda: False)

        post_helpers._schema_refresh(SimpleNamespace())
        assert ("yoke_core.domain.schema", ("init",)) in calls
        assert ("yoke_core.domain.shepherd", ("init",)) in calls
