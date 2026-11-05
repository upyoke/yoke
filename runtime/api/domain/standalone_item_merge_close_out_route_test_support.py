# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

from yoke_core.domain import release_wait_park

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge as sim

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)

from yoke_core.domain import standalone_item_merge_verify as verify

from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

LANE_SHA = "1" * 40

MERGE_SHA = "2" * 40


def _item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "deployment_flow": "prod-default",
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-7", "path": "/repo/.worktrees/ITEM-7"}],
    }


def _wire(monkeypatch, *, route):
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: (LANE_SHA, ""))
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(merge_cli.evidence, "record", lambda **_k: "")
    monkeypatch.setattr(sim, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli.release_flow,
        "continue_prepared_release",
        lambda **_k: (None, ""),
    )
    monkeypatch.setattr(merge_cli.close_out.terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery,
        "claim_error",
        lambda *_a: "",
    )
    calls: list = []

    def dispatch(*, function_id, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        close_out_transition,
        "close_out_route",
        lambda *_a, **_k: route,
    )
    retained: list = []

    def record(envelope, **kw):
        retained.append(kw)
        envelope.setdefault("release_wait", {"parked": "yes"})

    monkeypatch.setattr(close_out_transition, "retain_for_delivery", record)
    # retain_if_waiting stays real, so the refusal paths exercise its own
    # release-wait test; only the two writes underneath it are stood in for.
    monkeypatch.setattr(release_wait_park, "retain_for_delivery", record)
    retirements: list = []
    monkeypatch.setattr(
        merge_cli,
        "record_terminal_lane_close_out",
        lambda *a, **kw: retirements.append((a, kw)),
    )
    cleared: list = []
    monkeypatch.setattr(
        merge_cli.pending,
        "clear_after_close_out",
        lambda item_id, _item: cleared.append(item_id) or "",
    )
    return calls, retirements, cleared, retained


def _run():
    return merge_cli.run(
        ["ITEM-7", "--result", "landed", "--verification", "suite green"],
    )
