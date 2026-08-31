"""Done-stage merge and delivery satisfiers refuse rather than skip.

The engine used to reach done printing "continuing without a merge" and
recording nothing. These lock in the replacement: every shape resolves a
named rung or returns a refusal, and a relay that could not answer
blocks exactly like a ladder that said no.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from yoke_core.engines import done_transition_satisfiers as satisfiers


class _Error:
    def __init__(self, message: str) -> None:
        self.message = message


class _Response:
    def __init__(self, result: Dict[str, Any] | None, *, success: bool = True,
                 error: _Error | None = None) -> None:
        self.result = result
        self.success = success
        self.error = error


@pytest.fixture
def calls(monkeypatch):
    recorded: list[dict] = []

    def _fake(*, function_id, target, payload):
        recorded.append(
            {"function_id": function_id, "item_id": target.item_id,
             "payload": payload}
        )
        return _Response(
            {
                "obligation": payload["obligation"],
                "satisfied": True,
                "rung_id": "merged_locally",
                "detail": "the lane branch merged into the trunk",
                "stamp_recorded": True,
            }
        )

    monkeypatch.setattr(satisfiers, "call_dispatcher", _fake)
    return recorded


def test_merge_evidence_sends_the_facts_only_the_engine_can_see(calls):
    assert satisfiers.check_merge_evidence(
        42, merge_ran=True, branch_already_merged=False, branch_exists=True,
    ) is None
    observed = calls[0]["payload"]["observed"]
    assert observed["observed:merge_recorded"]["present"] is True
    assert observed["observed:no_implementation_branch"]["present"] is False
    assert calls[0]["item_id"] == 42


def test_no_branch_and_no_merge_reports_the_attestable_shape(calls):
    satisfiers.check_merge_evidence(
        42, merge_ran=False, branch_already_merged=False, branch_exists=False,
    )
    observed = calls[0]["payload"]["observed"]
    assert observed["observed:no_implementation_branch"]["present"] is True


def test_an_unmerged_existing_branch_is_not_attestable(calls):
    satisfiers.check_merge_evidence(
        42, merge_ran=False, branch_already_merged=False, branch_exists=True,
    )
    observed = calls[0]["payload"]["observed"]
    assert observed["observed:merge_recorded"]["present"] is False
    assert observed["observed:no_implementation_branch"]["present"] is False


def test_a_refusal_comes_back_as_the_narrative_to_block_on(monkeypatch):
    monkeypatch.setattr(
        satisfiers, "call_dispatcher",
        lambda **_: _Response(
            {"obligation": "done_merge_evidence", "satisfied": False,
             "refusal": "Merge the lane first."}
        ),
    )
    block = satisfiers.check_merge_evidence(
        42, merge_ran=False, branch_already_merged=False, branch_exists=True,
    )
    assert block == "Merge the lane first."


def test_a_satisfied_resolution_with_no_stamp_still_passes(monkeypatch, capsys):
    monkeypatch.setattr(
        satisfiers, "call_dispatcher",
        lambda **_: _Response(
            {"satisfied": True, "rung_id": "merged_locally", "detail": "d",
             "stamp_recorded": False}
        ),
    )
    assert satisfiers.check_merge_evidence(
        42, merge_ran=True, branch_already_merged=False, branch_exists=True,
    ) is None
    assert "not recorded on the item" in capsys.readouterr().out


def test_a_failed_relay_raises_rather_than_reporting_satisfied(monkeypatch):
    monkeypatch.setattr(
        satisfiers, "call_dispatcher",
        lambda **_: _Response(None, success=False, error=_Error("relay down")),
    )
    with pytest.raises(satisfiers.SatisfierRelayUnavailable) as excinfo:
        satisfiers.check_merge_evidence(
            42, merge_ran=True, branch_already_merged=False, branch_exists=True,
        )
    assert "relay down" in str(excinfo.value)
    assert "not the same answer" in str(excinfo.value)


def test_delivery_evidence_reports_the_merge_fact(calls):
    assert satisfiers.check_delivery_evidence(42, merge_recorded=True) is None
    observed = calls[0]["payload"]["observed"]
    assert observed["observed:merge_recorded"]["present"] is True
    assert calls[0]["payload"]["obligation"] == "delivery_evidence"


def test_both_obligations_resolve_in_order(calls):
    assert satisfiers.check_done_satisfiers(
        42, merge_ran=True, branch_already_merged=False, branch_exists=True,
    ) is None
    assert [c["payload"]["obligation"] for c in calls] == [
        "done_merge_evidence", "delivery_evidence",
    ]


def test_delivery_is_not_asked_when_merge_evidence_refuses(monkeypatch):
    seen: list[str] = []

    def _fake(*, function_id, target, payload):
        seen.append(payload["obligation"])
        return _Response({"satisfied": False, "refusal": "nope"})

    monkeypatch.setattr(satisfiers, "call_dispatcher", _fake)
    assert satisfiers.check_done_satisfiers(
        42, merge_ran=False, branch_already_merged=False, branch_exists=True,
    ) == "nope"
    assert seen == ["done_merge_evidence"]


def test_a_relay_failure_becomes_a_block_narrative_for_the_runner(monkeypatch):
    monkeypatch.setattr(
        satisfiers, "call_dispatcher",
        lambda **_: _Response(None, success=False, error=_Error("boom")),
    )
    block = satisfiers.check_done_satisfiers(
        42, merge_ran=True, branch_already_merged=False, branch_exists=False,
    )
    assert block is not None and "boom" in block
