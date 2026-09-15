"""The merge boundary lands at its pinned release wait, not at ``done``.

Exercises the actual CLI orchestration (``yoke merge item``'s ``run()``),
not just the isolated redirect-target resolution already covered in
``test_standalone_item_merge_release_status.py``: a redirect must report the
item's real resulting status and must not run the ``done``-only lane/claim
retirement, while a resolved-clear item still gets both.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_close_out_transition as close_out_transition
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

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


def _wire(monkeypatch, *, redirect_stage_id):
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
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
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, ""),
    )
    monkeypatch.setattr(merge_cli.close_out.terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery, "claim_error", lambda *_a: "",
    )
    calls: list = []

    def dispatch(*, function_id, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        close_out_transition, "release_redirect_stage",
        lambda *_a: (redirect_stage_id, ""),
    )
    retirements: list = []
    monkeypatch.setattr(
        merge_cli, "record_terminal_lane_close_out",
        lambda *a, **kw: retirements.append((a, kw)),
    )
    cleared: list = []
    monkeypatch.setattr(
        merge_cli.pending, "clear_after_close_out",
        lambda item_id, _item: cleared.append(item_id) or "",
    )
    return calls, retirements, cleared


def _run():
    return merge_cli.run(
        ["ITEM-7", "--result", "landed", "--verification", "suite green"],
    )


def test_a_pending_release_wait_lands_there_and_keeps_the_lane_and_claim(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared = _wire(monkeypatch, redirect_stage_id="release")

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "release"
    payloads = dict(calls)
    assert payloads["lifecycle.transition.execute"]["target_status"] == "release"
    assert retirements == []
    assert cleared == []


def test_a_delivery_already_clear_still_closes_out_and_retires_the_lane(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared = _wire(monkeypatch, redirect_stage_id=None)

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    payloads = dict(calls)
    assert payloads["lifecycle.transition.execute"]["target_status"] == "done"
    assert len(retirements) == 1
    assert cleared == [7]


def test_mid_progress_work_stays_at_its_own_status(monkeypatch, capsys) -> None:
    """A still-implementing Blitz slice: not forced to release by stage
    order alone, and not treated as an error either."""
    calls, retirements, cleared = _wire(monkeypatch, redirect_stage_id="reviewing-implementation")

    exit_code = _run()

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "reviewing-implementation"
    assert calls == []
    assert retirements == []
    assert cleared == []


def test_an_unresolved_delivery_clearance_refuses_rather_than_guesses(
    monkeypatch, capsys,
) -> None:
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
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
        merge_cli.release_flow, "continue_prepared_release", lambda **_k: (None, ""),
    )
    monkeypatch.setattr(
        close_out_transition, "release_redirect_stage",
        lambda *_a: (None, "the pinned workflow definition could not be read"),
    )
    monkeypatch.setattr(
        merge_cli.close_out.terminal,
        "call_dispatcher",
        lambda **_k: (_ for _ in ()).throw(
            AssertionError("an unresolved clearance must not attempt a transition")
        ),
    )

    exit_code = _run()

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert envelope["ok"] is False
    assert "delivery clearance could not be resolved" in envelope["error"]
