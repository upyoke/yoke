"""Transport-aware routing tests for the harness-universal worktree preflight.

The blocked-gate read and project-checkout resolution route through the
transport-aware relay so preflight works over an https control plane, not
only a local Postgres connection. The repo-layout builder and step-patching
helper are reused from :mod:`runtime.api.domain.test_worktree_preflight`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import worktree_preflight as wp
from runtime.api.domain.test_worktree_preflight import (
    _build_repo_layout,
    _patch_steps,
)


@pytest.fixture
def repo_layout(tmp_path):
    return _build_repo_layout(tmp_path)


class TestTransportAwareControlPlane:
    """The blocked-gate read and project-checkout resolution route through
    the transport-aware relay so preflight works over an https control
    plane, not only a local Postgres connection."""

    def _patch_detail(self, monkeypatch, item):
        from yoke_core.api import service_client_structured_api_adapter as facade

        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return FunctionCallResponse(
                success=True, function="items.detail.get", version="v1",
                result={"item": item},
            )

        monkeypatch.setattr(facade, "call_dispatcher", fake)
        return calls

    def test_blocked_gate_sources_from_items_detail_relay(
        self, repo_layout, monkeypatch
    ):
        _patch_steps(monkeypatch)
        calls = self._patch_detail(
            monkeypatch,
            {"blocked": True, "blocked_reason": "upstream coordination"},
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
        )
        assert outcome.ok is False
        assert outcome.block_kind == "blocked-flag"
        assert "items.blocked=1" in outcome.narrative
        assert "upstream coordination" in outcome.narrative
        assert any(c["function_id"] == "items.detail.get" for c in calls)

    def test_blocked_gate_degrades_when_relay_refuses(
        self, repo_layout, monkeypatch
    ):
        _patch_steps(monkeypatch)
        from yoke_core.api import service_client_structured_api_adapter as facade

        monkeypatch.setattr(
            facade, "call_dispatcher",
            lambda **_k: FunctionCallResponse(
                success=False, function="items.detail.get", version="v1",
            ),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            repo_root=repo_layout.root,
            session_id="sess",
            actual_cwd=repo_layout.root,
            no_worktree=True,
        )
        # A refused read must not block; the gate degrades and proceeds.
        assert outcome.ok is True

    def test_project_checkout_resolved_via_transport_aware_relay(
        self, repo_layout, monkeypatch
    ):
        _patch_steps(monkeypatch)
        # Blocked-gate read: not blocked, so the flow reaches the checkout
        # branch and the worktree steps.
        self._patch_detail(monkeypatch, {"blocked": False})

        from yoke_core.domain import project_checkout_locations as pcl

        resolved = []
        monkeypatch.setattr(
            pcl, "checkout_for_project_slug",
            lambda project, **_kw: resolved.append(project)
            or Path(repo_layout.root),
        )
        outcome = wp.run_preflight(
            item_id=9001,
            project="yoke",
            session_id="sess",
            actual_cwd=repo_layout.root,
            no_worktree=True,
        )
        assert outcome.ok is True
        assert resolved == ["yoke"]
