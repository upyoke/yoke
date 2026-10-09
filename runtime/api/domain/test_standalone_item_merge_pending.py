"""The item merge CLI treats queue admission as a non-terminal success."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pathlib import Path

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_pending as pending
from yoke_core.domain.merge_queue_landing_outcome import QueueLandingOutcome
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome


def test_pending_landing_exits_without_evidence_or_terminal_transition(
    monkeypatch,
    capsys,
):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/lane", "branch": "ITEM-1"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    observed_wait: list[bool] = []

    def enqueue(_item, args, **_kwargs):
        observed_wait.append(args.wait)
        return StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha="1" * 40,
            landing_pending=True,
            pr_num="42",
            enqueued_at="2026-08-27T18:00:00Z",
        ), ""

    monkeypatch.setattr(merge_cli.verify, "verify_and_land", enqueue)
    monkeypatch.setattr(
        merge_cli.evidence,
        "record",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("pending landing must not record evidence")
        ),
    )
    monkeypatch.setattr(
        merge_cli.close_out,
        "transition_to_done",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("pending landing must not transition")
        ),
    )

    rc = merge_cli.run(["ITEM-1", "--result", "queued", "--verification", "green"])

    assert rc == 0
    assert observed_wait == [False]
    payload = json.loads(capsys.readouterr().out)
    assert payload["landing_pending"] is True
    assert payload["pr_number"] == "42"
    assert payload["evidence_recorded"] is False
    assert payload["enqueued_at"] == "2026-08-27T18:00:00.000000Z"


def test_wait_flag_reaches_the_landing_route(monkeypatch):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/lane", "branch": "ITEM-1"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)

    def refuse(_item, args, **_kwargs):
        assert args.wait is True
        return None, "stop after parser assertion"

    monkeypatch.setattr(merge_cli.verify, "verify_and_land", refuse)
    assert (
        merge_cli.run(
            [
                "ITEM-1",
                "--wait",
                "--result",
                "r",
                "--verification",
                "v",
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    "clock",
    [
        "2026-10-09T10:11:12.345678Z",
        "2026-10-09T15:56:12.345678+05:45",
        None,
    ],
)
def test_queue_outcomes_keep_native_clock_until_pending_json(clock):
    instant = None if clock is None else parse_instant(clock)
    queued = QueueLandingOutcome(ok=True, exit_code=0, enqueued_at=clock)
    outcome = StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=False,
        enqueued_at=queued.enqueued_at,
        commit_sha="opaque sha",
        pr_num="opaque pr",
        warnings=("opaque warning",),
    )
    assert queued.enqueued_at == outcome.enqueued_at == instant
    if instant is not None:
        assert outcome.enqueued_at.utcoffset() == timedelta(0)
    payload = json.loads(
        json.dumps(
            pending.envelope(
                item_id=7,
                public_ref="ITEM-1",
                branch="opaque branch",
                target="main",
                status="review",
                outcome=outcome,
            )
        )
    )
    assert payload["enqueued_at"] == (
        None if instant is None else format_instant(instant)
    )
    assert payload["commit_sha"] == "opaque sha"
    assert payload["pr_number"] == "opaque pr"
    assert payload["warnings"] == ["opaque warning"]


@pytest.mark.parametrize(
    "clock",
    [
        "",
        "2026-10-09",
        "2026-10-09T10:11:12",
        "2026-10-09T10:11:12-00:00",
    ],
)
def test_queue_outcome_constructor_refuses_unqualified_clock(clock):
    with pytest.raises(InvalidInstant):
        QueueLandingOutcome(ok=True, exit_code=0, enqueued_at=clock)
    with pytest.raises(InvalidInstant):
        StandaloneMergeOutcome(
            ok=True, exit_code=0, already_merged=False, enqueued_at=clock
        )
