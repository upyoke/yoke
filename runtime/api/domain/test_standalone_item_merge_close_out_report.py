"""Every standalone-merge exit names its close-out outcome for a person."""

from __future__ import annotations

from runtime.api.domain.standalone_item_merge_close_out_report_test_support import (
    LANE_SHA as LANE_SHA,
    MERGE_SHA as MERGE_SHA,
    SESSION as SESSION,
    _item as _item,
    _outcome_block as _outcome_block,
    _response as _response,
    _run_close_out as _run_close_out,
)


import pytest

from yoke_core.domain import standalone_item_merge_close_out_report as report


def _holder_dispatch(holder):
    def dispatch(*, function_id, target, payload=None, **_kw):
        assert function_id == report.HOLDER_FUNCTION
        return _response({"holder": holder})

    return dispatch


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
    exit_code = report.fail_json(
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
    report.fail_json("ITEM-1: stale lane", as_json=True, public_ref="ITEM-1")

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
    assert report.claim_state("ITEM-7", SESSION, _holder_dispatch(holder)) == expected


def test_an_unreadable_holder_is_unconfirmed_rather_than_released():
    def refused(**_kw):
        return _response(success=False, message="relay unavailable")

    def raised(**_kw):
        raise RuntimeError("transport closed")

    assert report.claim_state("ITEM-7", SESSION, refused) == (
        "unconfirmed (relay unavailable)"
    )
    assert report.claim_state("ITEM-7", SESSION, raised) == (
        "unconfirmed (transport closed)"
    )


def test_a_merge_awaiting_delivery_is_not_reported_as_closed():
    kind, blocker = report.final_outcome(
        {
            "public_ref": "ITEM-1",
            "status": "release",
            "release_wait": {"parked": "yes", "park_reason": "awaiting delivery"},
        },
        source_status="reviewing-implementation",
        skip_status=False,
    )

    assert kind == report.AWAITING_DELIVERY
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
    state = report.claim_state("ITEM-7", SESSION, _holder_dispatch(holder))

    assert state.startswith("unconfirmed") or state == "held by session unknown"


def test_an_unresolvable_ambient_identity_is_unconfirmed(monkeypatch):
    def raised():
        raise RuntimeError("no ambient session")

    monkeypatch.setattr(report, "resolve_ambient_session_id", raised)
    state = report.claim_state(
        "ITEM-7", "", _holder_dispatch({"session_id": "other", "item_id": 7})
    )

    assert state == "unconfirmed (no ambient session)"


def test_an_unusable_item_id_is_unconfirmed_rather_than_raised():
    def unreached(**_kw):  # pragma: no cover - the conversion fails first
        raise AssertionError("dispatch should not be reached")

    assert report.claim_state("not-an-id", SESSION, unreached).startswith(
        "unconfirmed ("
    )


def test_an_unresolved_item_is_not_given_a_public_reference(capsys):
    report.fail_json("could not resolve item '9999': no such item", as_json=False)

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == f"{report.UNRESOLVED_REF} not closed"
    assert "  blocker: could not resolve item '9999': no such item" in block
