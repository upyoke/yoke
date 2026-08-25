"""Landed standalone merges reconstruct their lane head from the landing."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain.standalone_item_merge_landed import LandedLane


LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
LANE = LandedLane(
    branch="ITEM-1",
    target="main",
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("feature.py",),
    source="merge receipt",
)


def _landed_item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [],
        "qa_plan_attachments": [],
        "qa_requirements": [],
    }


@pytest.mark.parametrize(
    "claim_state",
    ["", "no live work claim on this item"],
    ids=["claim-pre-held", "claim-self-acquired"],
)
def test_pruned_lane_reconstructs_the_same_receipt_head(
    claim_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (_landed_item(), ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: claim_state)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(recovery, "branch_needs_receipt", lambda *_a: True)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    recovery_calls: list[dict] = []

    def recover(**kwargs):
        recovery_calls.append(kwargs)
        return LANE, ""

    monkeypatch.setattr(recovery, "reacquire_landed_claim", recover)
    preflight_heads: list[str] = []

    def preflight(item, **_kwargs):
        preflight_heads.append(item["worktrees"][-1]["commit_sha"])
        return LANE_SHA, ""

    monkeypatch.setattr(verify, "qa_preflight", preflight)
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_kwargs: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=True,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)

    assert merge_cli.run(["ITEM-1", "--skip-status"]) == 0
    assert preflight_heads == [LANE_SHA]
    assert len(recovery_calls) == 1


def test_released_only_history_still_recovers_from_the_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Released rows are not a live lane; receipt recovery still applies."""
    item = {
        **_landed_item(),
        "worktrees": [{
            "branch": "ITEM-1",
            "state": "released",
            "commit_sha": "a" * 40,
        }],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(
        merge_cli, "_session_holds_claim",
        lambda *_a: "no live work claim on this item",
    )
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(recovery, "branch_needs_receipt", lambda *_a: True)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        recovery, "reacquire_landed_claim", lambda **_k: (LANE, ""),
    )
    recovered: list[str] = []

    def preflight(recovered_item, **_kwargs):
        recovered.append(recovered_item["worktrees"][-1]["commit_sha"])
        return LANE_SHA, ""

    monkeypatch.setattr(verify, "qa_preflight", preflight)
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_kwargs: StandaloneMergeOutcome(
            ok=True, exit_code=0, already_merged=True, commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA, touched_files=("feature.py",), pushed=True,
        ),
    )
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)

    assert merge_cli.run(["ITEM-1", "--skip-status"]) == 0
    assert recovered == [LANE_SHA]


def test_live_branch_does_not_enter_receipt_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = {
        **_landed_item(),
        "worktrees": [{"branch": "ITEM-1", "state": "active", "commit_sha": LANE_SHA}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (live, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(recovery, "branch_needs_receipt", lambda *_a: False)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        recovery,
        "reacquire_landed_claim",
        lambda **_kwargs: pytest.fail("a live branch needs no claim recovery"),
    )
    monkeypatch.setattr(
        verify,
        "qa_preflight",
        lambda *_a, **_kwargs: (LANE_SHA, ""),
    )
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_kwargs: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda _item_id: None)

    assert merge_cli.run(["ITEM-1", "--skip-status"]) == 0
