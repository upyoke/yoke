"""Every standalone-merge exit names its close-out outcome for a person."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import (
    standalone_item_merge_close_out_report as report,
)
from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
SESSION = "session-under-test"


def _response(result=None, *, success=True, message=""):
    error = None if success else SimpleNamespace(message=message)
    return SimpleNamespace(success=success, result=result or {}, error=error)


def _holder_dispatch(holder):
    def dispatch(*, function_id, target, payload=None, **_kw):
        assert function_id == report.HOLDER_FUNCTION
        return _response({"holder": holder})

    return dispatch


def _outcome_block(captured_err: str) -> list[str]:
    prefix = f"{report.LINE_PREFIX} "
    return [
        line[len(prefix) :]
        for line in captured_err.splitlines()
        if line.startswith(prefix)
    ]


def _item(status: str = "reviewing-implementation") -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": status,
        "workflow": {"id": "dash", "terminal_stage_ids": ["done"]},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/.worktrees/ITEM-1", "branch": "ITEM-1"}],
    }


def _run_close_out(
    monkeypatch, *, holder=None, argv=None, holder_dispatch=None
) -> None:
    """Drive a complete merge whose close-out reaches the terminal status."""
    item = _item()
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(merge_cli.landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main")
    )
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
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
            touched_files=("a.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda _item_id: None)
    monkeypatch.setattr(git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(
        merge_cli, "record_terminal_lane_close_out", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        close_out_transition, "close_out_route", lambda *_a: CloseOutRoute(stages=("done",))
    )

    def dispatch(*, function_id, target, payload=None, **_kw):
        if function_id == report.HOLDER_FUNCTION:
            if holder_dispatch is not None:
                return holder_dispatch(function_id=function_id, target=target)
            return _response({"holder": holder})
        return _response()

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_cli.close_out.terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        merge_cli.close_out.terminal.recovery, "claim_error", lambda *_a: ""
    )
    exit_code = merge_cli.run(
        argv
        or [
            "ITEM-1",
            "--result",
            "landed",
            "--verification",
            "green",
            "--session-id",
            SESSION,
        ]
    )
    assert exit_code == 0


def test_a_completed_close_out_names_the_item_evidence_and_claim(monkeypatch, capsys):
    _run_close_out(monkeypatch)

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 closed: done"
    assert f"  evidence saved: yes — {report.EVIDENCE_WRITTEN_NOTE}" in block
    assert "  work claim: released" in block


def test_a_claim_the_close_out_did_not_release_is_reported_as_held(monkeypatch, capsys):
    _run_close_out(monkeypatch, holder={"session_id": SESSION, "item_id": 7})

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 closed: done"
    assert "  work claim: still held by this session" in block


def test_a_merge_that_skips_close_out_does_not_report_a_closed_item(
    monkeypatch, capsys
):
    _run_close_out(
        monkeypatch,
        argv=["ITEM-1", "--skip-status", "--session-id", SESSION],
    )

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 not closed"
    assert any("--skip-status" in line for line in block)
    assert "  evidence saved: no" in block


def test_a_refusal_names_not_closed_and_its_blocker(capsys):
    exit_code = merge_cli._fail(
        "ITEM-1: work claim held by another session (other)",
        as_json=False,
        public_ref="ITEM-1",
    )

    assert exit_code == 1
    block = _outcome_block(capsys.readouterr().err)
    assert block == [
        "ITEM-1 not closed",
        "  blocker: ITEM-1: work claim held by another session (other)",
    ]


def test_a_refusal_reports_no_effect_it_did_not_confirm(capsys):
    merge_cli._fail("ITEM-1: stale lane", as_json=True, public_ref="ITEM-1")

    block = _outcome_block(capsys.readouterr().err)
    assert not [line for line in block if "evidence saved" in line]
    assert not [line for line in block if "work claim" in line]


def test_an_item_that_was_already_closed_says_this_run_changed_nothing():
    lines = report.outcome_lines(
        {
            "item_id": 7,
            "public_ref": "ITEM-1",
            "status": "done",
            "evidence_recorded": True,
        },
        kind=report.ALREADY_CLOSED,
        evidence_from_record=True,
    )

    assert lines[0] == "ITEM-1 already closed: done — this run did not close it"
    assert "  evidence saved: recorded before this run" in lines


def test_a_pending_landing_names_its_pull_request_and_re_entry():
    lines = report.outcome_lines(
        {
            "item_id": 7,
            "public_ref": "ITEM-1",
            "status": "reviewing-implementation",
            "landing_pending": True,
            "pr_number": "42",
            "evidence_recorded": False,
        },
        kind=report.LANDING_PENDING,
    )

    assert lines[0] == "ITEM-1 not closed: landing pending"
    assert any("pull request #42" in line for line in lines)
    assert "  evidence saved: no" in lines


def test_partial_failures_reach_the_block_as_warnings():
    lines = report.outcome_lines(
        {
            "item_id": 7,
            "public_ref": "ITEM-1",
            "status": "done",
            "evidence_recorded": True,
            "warnings": ["GitHub sync skipped: no token"],
        },
        kind=report.CLOSED,
    )

    assert "  warning: GitHub sync skipped: no token" in lines


@pytest.mark.parametrize(
    ("holder", "expected"),
    (
        (None, "released"),
        ({"session_id": SESSION, "item_id": 7}, "still held by this session"),
        ({"session_id": "other", "item_id": 7}, "held by session other"),
    ),
)
def test_the_claim_line_reports_the_live_holder(holder, expected):
    assert report.claim_state(7, SESSION, _holder_dispatch(holder)) == expected


def test_an_unreadable_holder_is_unconfirmed_rather_than_released():
    def refused(**_kw):
        return _response(success=False, message="relay unavailable")

    def raised(**_kw):
        raise RuntimeError("transport closed")

    assert report.claim_state(7, SESSION, refused) == (
        "unconfirmed (relay unavailable)"
    )
    assert report.claim_state(7, SESSION, raised) == ("unconfirmed (transport closed)")


def test_a_merge_awaiting_delivery_is_not_reported_as_closed():
    kind, blocker = report.final_outcome(
        {"public_ref": "ITEM-1", "status": "release"},
        source_status="reviewing-implementation",
        skip_status=False,
    )

    assert kind == report.NOT_CLOSED
    assert "the merge landed and the item is at release" in blocker


def test_a_re_entry_on_an_already_done_item_does_not_claim_the_close():
    kind, _blocker = report.final_outcome(
        {"public_ref": "ITEM-1", "status": "done"},
        source_status="done",
        skip_status=False,
    )

    assert kind == report.ALREADY_CLOSED


def test_a_malformed_holder_cannot_turn_a_closed_item_into_a_failure(
    monkeypatch, capsys
):
    """Reporting runs after the item is closed; it must not raise there."""

    def malformed(**_kw):
        return _response({"holder": ["not", "a", "mapping"]})

    _run_close_out(monkeypatch, holder_dispatch=malformed)

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 closed: done"
    assert (
        f"  work claim: unconfirmed ({report.HOLDER_FUNCTION} returned a malformed holder)"
        in block
    )


def test_a_holder_read_that_raises_cannot_fail_a_closed_item(monkeypatch, capsys):
    def raised(**_kw):
        raise RuntimeError("relay socket closed")

    _run_close_out(monkeypatch, holder_dispatch=raised)

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 closed: done"
    assert "  work claim: unconfirmed (relay socket closed)" in block


@pytest.mark.parametrize(
    "holder", ("a-session-string", ["list"], 7, {"no_session": True})
)
def test_a_holder_shape_this_build_does_not_expect_is_unconfirmed(holder):
    state = report.claim_state(7, SESSION, _holder_dispatch(holder))

    assert state.startswith("unconfirmed") or state == "held by session unknown"


def test_an_unresolvable_ambient_identity_is_unconfirmed(monkeypatch):
    def raised():
        raise RuntimeError("no ambient session")

    monkeypatch.setattr(report, "resolve_ambient_session_id", raised)
    state = report.claim_state(
        7, "", _holder_dispatch({"session_id": "other", "item_id": 7})
    )

    assert state == "unconfirmed (no ambient session)"


def test_an_unusable_item_id_is_unconfirmed_rather_than_raised():
    def unreached(**_kw):  # pragma: no cover - the conversion fails first
        raise AssertionError("dispatch should not be reached")

    assert report.claim_state("not-an-id", SESSION, unreached).startswith(
        "unconfirmed ("
    )


def test_an_unresolved_item_is_not_given_a_public_reference(capsys):
    merge_cli._fail("could not resolve item '9999': no such item", as_json=False)

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == f"{report.UNRESOLVED_REF} not closed"
    assert "  blocker: could not resolve item '9999': no such item" in block
