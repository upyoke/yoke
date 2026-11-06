"""The local runner resets before a chain and restores after it ends."""

from __future__ import annotations

from runtime.api.domain.machine_qa_chain_restore_test_support import (
    _contract as _contract,
    _run as _run,
)


from types import SimpleNamespace

import pytest


def test_a_chain_end_resets_first_and_restores_after(monkeypatch) -> None:
    row, reached, ran = _run(monkeypatch, _contract(baselines=["fresh-host"]))
    assert reached == ["fresh-host", "fresh-host"]
    assert ran == [11]
    assert row["evidence"]["starting_state_restore"]["restored"] is True


def test_a_passing_case_inside_a_chain_leaves_the_machine_for_its_follower(
    monkeypatch,
) -> None:
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    row, reached, _ = _run(monkeypatch, contract)
    assert reached == ["fresh-host"]
    assert "starting_state_restore" not in row["evidence"]


def test_a_failed_case_restores_even_when_its_chain_continues(monkeypatch) -> None:
    contract = _contract(baselines=[], starting_state="inherit", ends_chain=False)
    row, reached, _ = _run(monkeypatch, contract, outcome="failed")
    assert reached == ["fresh-host"]
    assert row["evidence"]["starting_state_restore"]["baseline"] == "fresh-host"


def test_a_failed_reset_leaves_the_case_unstarted_and_blocked(monkeypatch) -> None:
    row, _, ran = _run(monkeypatch, _contract(baselines=["fresh-host"]), reset_ok=False)
    assert ran == []
    assert row["case_outcome"] == "blocked_on_precondition"
    assert row["error_code"] == "starting_state_reset_failed"
    assert row["evidence"]["case_started"] is False
    assert row["evidence"]["starting_state_reset"]["ok"] is False


def test_an_as_is_chain_records_that_nothing_can_be_restored(monkeypatch) -> None:
    contract = _contract(baselines=[], starting_state="as_is")
    row, reached, _ = _run(monkeypatch, contract)
    assert reached == []
    restore = row["evidence"]["starting_state_restore"]
    assert restore["restored"] is False
    assert "no declared starting state" in restore["reason"]


def test_a_local_error_still_restores_and_says_so(monkeypatch) -> None:
    with pytest.raises(RuntimeError) as raised:
        _run(
            monkeypatch,
            _contract(baselines=["fresh-host"]),
            raises=RuntimeError("terminal bridge lost"),
        )
    assert "starting state restored to 'fresh-host'" in raised.value.__notes__


@pytest.mark.parametrize("ends_chain", [False, True])
def test_successful_pending_review_capture_preserves_only_intermediate_state(
    monkeypatch,
    ends_chain,
):
    row, reached, _ = _run(
        monkeypatch,
        _contract(baselines=["fresh-host"], ends_chain=ends_chain),
        outcome="needs_review",
    )
    assert row["case_outcome"] == "needs_review"
    assert row["verdict"] == "pending"
    assert reached == ["fresh-host"] * (2 if ends_chain else 1)
    assert ("starting_state_restore" in row["evidence"]) == ends_chain


@pytest.mark.parametrize(
    "capture",
    [
        {"case_outcome": "needs_review", "error_code": "capture_failed"},
        {"case_outcome": "needs_review", "execution_status": "capture_failed"},
        {"case_outcome": "needs_review", "verdict": "fail"},
        {"case_outcome": "waiting"},
        {"case_outcome": "error"},
    ],
)
def test_unsuccessful_capture_never_permits_chain_continuation(capture):
    from yoke_core.domain.machine_qa_chain_restore import (
        capture_allows_chain,
        restore_due,
    )

    assert not capture_allows_chain(capture)
    assert restore_due(SimpleNamespace(ends_chain=False), **capture)
