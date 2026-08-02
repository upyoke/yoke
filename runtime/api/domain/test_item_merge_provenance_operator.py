"""Operator repair of a terminal item's unset merge timestamp.

The surface exists because terminal items are immutable and a branch that
lands outside the merge boundary leaves ``merged_at`` unset forever. These
tests pin the guardrails that keep it from widening into the general
terminal write path the contract excludes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.item_merge_provenance_operator import (
    MergedAtCorrectionError,
    MergedAtCorrectionHookContextError,
    operator_correct_merged_at,
)

ITEM_ID = 4101
LANDED_AT = "2026-08-01T18:42:00Z"
REASON = "branch landed via gh pr merge; PR merge path unavailable"


def _merged_at(conn) -> str:
    row = conn.execute(
        "SELECT merged_at FROM items WHERE id = %s", (ITEM_ID,)
    ).fetchone()
    value = row["merged_at"] if hasattr(row, "keys") else row[0]
    return str(value or "")


def _seed(conn, *, status: str = "done", merged_at=None) -> None:
    insert_item(
        conn,
        id=ITEM_ID,
        title="Item that landed outside the merge boundary",
        workflow_id="dash",
        status=status,
        merged_at=merged_at,
    )


def test_fills_unset_merged_at_on_terminal_item(test_db):
    _seed(test_db)

    result = operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert result["corrected"] is True
    assert result["merged_at"] == LANDED_AT
    assert result["operator_reason"] == REASON
    assert _merged_at(test_db) == LANDED_AT


def test_reported_ref_comes_from_project_sequence_not_row_id(test_db):
    """The summary names the public ref, which is not the internal row id."""
    insert_item(
        conn=test_db,
        id=ITEM_ID,
        title="Item whose row id and public number differ",
        workflow_id="dash",
        status="done",
        project_sequence=ITEM_ID - 7,
    )

    result = operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert result["item_ref"].endswith(str(ITEM_ID - 7))
    assert not result["item_ref"].endswith(str(ITEM_ID))


def test_refuses_when_merged_at_already_recorded(test_db):
    _seed(test_db, merged_at="2026-07-30T09:00:00Z")

    with pytest.raises(MergedAtCorrectionError, match="already records merged_at"):
        operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert _merged_at(test_db) == "2026-07-30T09:00:00Z"


def test_refuses_a_non_terminal_item(test_db):
    _seed(test_db, status="implementing")

    with pytest.raises(MergedAtCorrectionError, match="not a terminal stage"):
        operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert _merged_at(test_db) == ""


def test_refuses_an_empty_operator_reason(test_db):
    _seed(test_db)

    with pytest.raises(MergedAtCorrectionError, match="operator_reason"):
        operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, "   ")

    assert _merged_at(test_db) == ""


def test_refuses_a_malformed_timestamp(test_db):
    _seed(test_db)

    with pytest.raises(MergedAtCorrectionError, match="must match"):
        operator_correct_merged_at(test_db, ITEM_ID, "2026-08-01 18:42", REASON)

    assert _merged_at(test_db) == ""


def test_refuses_a_future_timestamp(test_db):
    _seed(test_db)
    ahead = datetime.now(timezone.utc) + timedelta(days=2)

    with pytest.raises(MergedAtCorrectionError, match="in the future"):
        operator_correct_merged_at(
            test_db, ITEM_ID, ahead.strftime("%Y-%m-%dT%H:%M:%SZ"), REASON
        )

    assert _merged_at(test_db) == ""


def test_refuses_a_hook_context(test_db, monkeypatch):
    _seed(test_db)
    monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")

    with pytest.raises(MergedAtCorrectionHookContextError, match="human-only"):
        operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert _merged_at(test_db) == ""


def test_refuses_an_unknown_item(test_db):
    with pytest.raises(MergedAtCorrectionError, match="does not exist"):
        operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)


def test_emits_the_warn_event_before_the_write_lands(test_db, monkeypatch):
    """Ledger-first: a telemetry outage must not mask a successful action."""
    _seed(test_db)
    observed: list[tuple[str, str, str]] = []

    def _capture(event_name, **kwargs):
        observed.append(
            (event_name, kwargs.get("severity", ""), _merged_at(test_db))
        )

    monkeypatch.setattr("yoke_core.domain.events.emit_event", _capture)

    operator_correct_merged_at(test_db, ITEM_ID, LANDED_AT, REASON)

    assert observed, "correction emitted no event"
    name, severity, merged_at_when_emitted = observed[0]
    assert name == "OperatorMergedAtCorrection"
    assert severity == "WARN"
    assert merged_at_when_emitted == ""
    assert _merged_at(test_db) == LANDED_AT
