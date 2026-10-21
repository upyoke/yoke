"""The steering report lists each QA settlement follow-up whose replay failed."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain import deployment_member_close_out_retry as close_out
from yoke_core.domain import qa_settlement_followups as followups
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.steering_fleet_report_settlement_followups import HEADING


@pytest.fixture
def scope(test_db: Any) -> Any:
    return seed_steering_scope(test_db)


def _owe(conn: Any, item_id: int) -> None:
    followups.request_settlement_followup(conn, item_id=item_id)
    conn.commit()


def test_a_failed_replay_is_listed_with_its_item_and_error(
    scope: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owe(scope, 1)

    def fail(_conn, *, item_id):
        raise RuntimeError("close-out gate unreadable")

    monkeypatch.setattr(close_out, "after_record_settled", fail)
    followups.replay_settlement_followups(scope)

    report = compose(scope)

    [row] = report.settlement_followups
    assert row.item_id == 1
    assert row.public_ref.endswith("-1")
    assert row.attempts == 1
    assert row.last_error == "RuntimeError: close-out gate unreadable"
    assert report.actionable
    body = report_body(report)
    assert f"{HEADING}:" in body
    assert (
        f"  {row.public_ref} after 1 attempt(s): "
        "RuntimeError: close-out gate unreadable"
    ) in body


def test_an_owed_follow_up_that_has_not_failed_is_not_listed(scope: Any) -> None:
    _owe(scope, 2)

    report = compose(scope)

    assert report.settlement_followups == ()
    assert HEADING not in report_body(report)
