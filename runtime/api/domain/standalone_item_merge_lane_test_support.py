# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from unittest import mock

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import standalone_item_merge_verify as verify

from yoke_core.domain import standalone_item_merge_qa as merge_qa

from yoke_core.domain import standalone_item_merge_recovery as recovery

from yoke_core.domain.standalone_item_merge_lane import (
    lane_branch,
    lane_path,
    lane_resolution_error,
    merge_source_lane,
)

from yoke_core.domain.item_merge_receipts import MergeReceipt

from yoke_core.domain.standalone_item_merge_recovery import with_recorded_head

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

ACTIVE_SHA = "b" * 40

OTHER_SHA = "c" * 40


@pytest.fixture(autouse=True)
def _enter_release_wait_on_close_out(monkeypatch):
    monkeypatch.setattr(
        merge_cli.close_out,
        "transition_to_done",
        lambda **kwargs: (
            (tuple(kwargs.get("stages") or ("release",)) or ("release",))[-1],
            "",
        ),
    )


def _item(worktrees: list[dict]) -> dict:
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": worktrees,
        "qa_plan_attachments": [],
        "qa_requirements": [],
    }


def _wire_cli(monkeypatch, item: dict, tmp_path: Path) -> mock.Mock:
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (tmp_path, "main"),
    )
    admit_route_gates(monkeypatch)
    outcome = merge_domain.StandaloneMergeOutcome(
        exit_code=0,
        ok=True,
        already_merged=False,
        commit_sha=ACTIVE_SHA,
        merge_sha=OTHER_SHA,
        touched_files=("file.py",),
        pushed=True,
        warnings=(),
    )
    merger = mock.Mock(return_value=outcome)
    monkeypatch.setattr(verify, "route_standalone_landing", merger)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)
    return merger
