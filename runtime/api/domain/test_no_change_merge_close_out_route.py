"""No-change close-out walks ``yoke merge item`` rather than a constructed lane."""

from __future__ import annotations

import json

from runtime.api.domain.test_standalone_item_merge_close_out_route import _run, _wire
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute


def _empty_outcome(**_k) -> StandaloneMergeOutcome:
    return StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=False,
        commit_sha="",
        merge_sha="",
        touched_files=(),
        pushed=False,
    )


def test_no_change_close_out_walks_the_cli_route_without_git_landing(
    monkeypatch, capsys,
) -> None:
    calls, retirements, cleared = _wire(
        monkeypatch,
        route=CloseOutRoute(
            stages=("release", "done"), delivery_discharged=True,
        ),
    )
    monkeypatch.setattr(verify, "route_standalone_landing", _empty_outcome)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.evidence,
        "attested_empty_landing",
        lambda _id: True,
    )
    monkeypatch.setattr(
        merge_cli.close_out.terminal.git,
        "is_landed",
        lambda *_a: (_ for _ in ()).throw(
            AssertionError("attested no-change must not inspect git")
        ),
    )

    exit_code = merge_cli.run(
        [
            "ITEM-7",
            "--result", "no code change",
            "--verification", "recorded no-changes",
            "--no-changes",
        ],
    )

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["status"] == "done"
    assert envelope["commit_sha"] == ""
    assert envelope["merge_sha"] == ""
    transitions = [
        payload for function_id, payload in calls
        if function_id == "lifecycle.transition.execute"
    ]
    assert [payload["done_nonce_verified"] for payload in transitions] == [
        False, True,
    ]
    assert len(retirements) == 1
    assert cleared == [7]


def test_empty_shas_without_no_change_evidence_refuse_the_cli_route(
    monkeypatch, capsys,
) -> None:
    _wire(
        monkeypatch,
        route=CloseOutRoute(stages=("done",), delivery_discharged=True),
    )
    monkeypatch.setattr(verify, "route_standalone_landing", _empty_outcome)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.evidence,
        "attested_empty_landing",
        lambda _id: False,
    )

    exit_code = _run()

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert envelope["ok"] is False
    assert "not reachable from 'main'" in envelope["error"]
