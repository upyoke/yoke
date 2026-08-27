"""The item merge CLI treats queue admission as a non-terminal success."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import standalone_item_merge_cli as merge_cli
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
        merge_cli.terminal,
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
