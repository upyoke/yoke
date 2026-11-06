# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_landing_readiness as readiness_gate

from yoke_core.domain import merge_review_readiness as review_gate

from yoke_core.domain import qa_item_stage_plan_gate as plan_gate

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane

from yoke_core.domain import standalone_item_merge_verify as verify

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

ITEM_SCOPED_QA = [{"name": "item-qa", "stage_kind": "qa", "scope": "item"}]


def _item(**overrides) -> dict:
    item = {
        "id": 51,
        "public_ref": "ITEM-51",
        "status": "implementing",
        "workflow": {"id": "dash", "version": 10},
        "project": {"slug": "yoke"},
        "completion_flow": "release-qa",
        "worktrees": [
            {"branch": "ITEM-51", "state": "active", "path": "/nonexistent/lane"}
        ],
        "qa_requirements": [],
        "qa_plan_attachments": [],
    }
    item.update(overrides)
    return item


@pytest.fixture
def merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Stub every control-plane and git read the gates make."""
    state = {"item": _item(), "transitions": [], "landed": 0}
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (state["item"], ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli, "_resolve_checkout", lambda *_a: (tmp_path, "main"))
    admit_route_gates(monkeypatch)
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(landed, "landed_lane", lambda **_k: None)
    monkeypatch.setattr(stale_lane, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: ("abc", ""))
    monkeypatch.setattr(plan_gate, "flow_stages", lambda _flow: (ITEM_SCOPED_QA, ""))
    monkeypatch.setattr(plan_gate, "attachment_transition", lambda _item: "release")
    monkeypatch.setattr(
        merge_cli,
        "enter_review_stage",
        lambda ref, review, *, reason: (
            state["transitions"].append(
                (review.source_stage, review.review_stage, reason)
            )
            or ""
        ),
    )

    def _verify(*_a, enter_review, **_k):
        refusal = enter_review()
        if refusal:
            return None, refusal
        state["landed"] += 1
        return None, "stop after landing was reached"

    monkeypatch.setattr(verify, "verify_and_land", _verify)
    return state


def _run(*extra: str) -> int:
    return merge_cli.run(["ITEM-51", "--session-id", "s-1", *extra])
