"""A re-entered close-out still owes the item's lanes their retirement.

Terminal status is committed before the machine-local retirement runs, and
that retirement can legitimately refuse — a dirty tree, a locked worktree,
an unreachable remote. Nothing retries it on a schedule, so the next run
that reaches the same terminal item is the retry. These prove the two
re-entry shapes take it rather than returning the recorded landing and
leaving the directory behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import standalone_item_merge_cli as merge_cli

CLAIM_MISSING = (
    "no active claim by session 'session-1' on item ITEM-1; acquire one "
    'first: yoke claims work acquire --item ITEM-1 --reason "<intent>"'
)


def _closed_out_item() -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "done",
        "workflow": {"id": "dash", "terminal_stage_ids": ["done", "cancelled"]},
        "project": {"id": 1, "slug": "yoke", "default_branch": "main"},
        "worktrees": [{"branch": "ITEM-1", "path": "/repo/.worktrees/ITEM-1"}],
    }


@pytest.fixture()
def retirements(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def retire(item, envelope, **kwargs):
        calls.append({"item": item, **kwargs})
        envelope["lane_sweep"] = {
            "removed": ["/repo/.worktrees/ITEM-1"],
            "preserved": [],
            "skipped": "",
        }

    monkeypatch.setattr(merge_cli, "record_terminal_lane_close_out", retire)
    return calls


def test_a_close_out_re_entered_after_its_claim_released_retires_lanes(
    monkeypatch,
    capsys: pytest.CaptureFixture,
    retirements: list[dict],
) -> None:
    """The item is already closed out; its lane may still be on disk."""
    item = _closed_out_item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: CLAIM_MISSING)
    monkeypatch.setattr(
        merge_cli.evidence,
        "closed_out_envelope",
        lambda *_a, **_k: {"ok": True, "public_ref": "ITEM-1", "warnings": []},
    )
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: pytest.fail("the closed-out re-entry answers before checkout"),
    )

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "suite green"]
    )

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["lane_sweep"]["removed"] == ["/repo/.worktrees/ITEM-1"]
    assert retirements[0]["target_status"] == "done"
    assert retirements[0]["item"]["public_ref"] == "ITEM-1"


def test_the_retirement_reads_the_checkout_the_merge_resolved(
    monkeypatch,
    capsys: pytest.CaptureFixture,
    retirements: list[dict],
) -> None:
    """A re-entry past checkout resolution passes what it already knows.

    Resolving the project checkout twice is wasted work, and the ``--target``
    override the merge honored is the branch the retirement must prove
    against.
    """
    item = _closed_out_item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "release")
    )
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(merge_cli.landed, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_k: None)
    monkeypatch.setattr(merge_cli.recovery, "branch_needs_receipt", lambda *_a: False)
    monkeypatch.setattr(
        merge_cli.verify,
        "verify_and_land",
        lambda *_a, **_k: pytest.fail("the recorded landing answers first"),
    )
    monkeypatch.setattr(
        merge_cli.evidence,
        "recorded_landing_envelope",
        lambda *_a, **_k: {"ok": True, "public_ref": "ITEM-1"},
    )
    # A landed lane whose own converge reports the landing already recorded.
    monkeypatch.setattr(
        merge_cli.evidence, "closed_out_envelope", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        merge_cli.close_out, "transition_to_done", lambda **_k: ("", "claim released")
    )
    monkeypatch.setattr(merge_cli.close_out, "record_execution_evidence", _no_write)
    monkeypatch.setattr(merge_cli.merge_domain, "sync_item_to_github", lambda _i: None)
    monkeypatch.setattr(
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, "")
    )
    monkeypatch.setattr(
        merge_cli.verify,
        "verify_and_land",
        lambda *_a, **_k: (_landed_outcome(), ""),
    )

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "suite green"]
    )

    assert exit_code == 0
    capsys.readouterr()
    assert retirements[0]["repo_root"] == Path("/repo")
    assert retirements[0]["target_branch"] == "release"


def _no_write(**_kwargs) -> tuple[str, str]:
    return "", ""


def _landed_outcome():
    class _Outcome:
        ok = True
        error = ""
        exit_code = 0
        already_merged = False
        commit_sha = "1" * 40
        merge_sha = "2" * 40
        touched_files = ("feature.txt",)
        pushed = True
        warnings = ()
        landing_pending = False

    return _Outcome()
