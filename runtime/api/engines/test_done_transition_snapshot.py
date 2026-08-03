"""Tests for done-transition path-snapshot prewarming.

The prewarm resolves the item's project slug and the machine-local
checkout through the connected transport, resolves the new HEAD locally
with git, and relays the snapshot write through ``project.snapshot.ensure_at``
so it works over an https control plane as well as a local Postgres
connection. These tests assert the checkout -> git -> relay wiring and the
advisory (never-raising) disposition; the routing regressions live in
``test_done_transition_writes_transport``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition_snapshot


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def test_ensure_snapshot_resolves_checkout_and_relays_write(monkeypatch):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        fid = kwargs["function_id"]
        if fid == "done_transition.item_field":
            return _resp(fid, {"value": "yoke"})
        return _resp(fid, {"project": "1", "commit_sha": "abc123", "snapshot_id": 7})

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fake
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda project, **_kwargs: Path("/repo/root"),
    )
    git_cmd = {}

    def fake_git(cmd, **_kwargs):
        git_cmd["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="abc123\n")

    monkeypatch.setattr(done_transition_snapshot.subprocess, "run", fake_git)

    done_transition_snapshot.ensure_snapshot_for_item(42)

    # The project slug read + snapshot write both relay through the transport.
    fids = [c["function_id"] for c in calls]
    assert fids[0] == "done_transition.item_field"
    assert "project.snapshot.ensure_at" in fids
    # HEAD is resolved from the transport-resolved machine-local checkout.
    assert git_cmd["cmd"] == ["git", "-C", "/repo/root", "rev-parse", "HEAD"]
    ensure = next(c for c in calls if c["function_id"] == "project.snapshot.ensure_at")
    assert ensure["payload"] == {"project": "yoke", "commit_sha": "abc123"}


def test_ensure_snapshot_advisory_on_missing_checkout(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **kwargs: _resp(kwargs["function_id"], {"value": "yoke"}),
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
        lambda project, **_kwargs: None,
    )
    # No checkout -> no git, no write; the prewarm stays advisory (no raise).
    done_transition_snapshot.ensure_snapshot_for_item(42)
