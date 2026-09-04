"""Parsers, against the envelope shapes the control plane actually returns.

This is the layer that fails silently: a parser reading a key the
control plane does not emit returns an empty snapshot, and an empty
snapshot produces no deltas — indistinguishable from a quiet fleet.
Every case below pins a key or field name to the live shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.fleet_delta_snapshot import (
    envelope_rows,
    item_rows,
    parse_timestamp,
    session_rows,
)


def test_session_rows_read_the_roster_rows_key() -> None:
    """`sessions.list` returns `fields` + `rows`; only `rows` carry state."""
    result = {
        "fields": ["session_id", "mode"],
        "rows": [
            {
                "session_id": "6dc9ec0d-8bc8-4447-aae6-4a5332884",
                "executor_surface": "claude-cli",
                "mode": "steer",
                "activity_at": "2026-08-28T17:00:00Z",
                "ended_at": None,
                "terminated_at": None,
                "quiet_reason": None,
                "claims": [
                    {"target_kind": "item", "target": "YOK-2571"},
                    {"target_kind": "process", "target": "DOCTOR"},
                ],
            }
        ],
    }
    rows = session_rows(result)
    row = rows["6dc9ec0d-8bc8-4447-aae6-4a5332884"]
    assert row.executor_surface == "claude-cli"
    assert row.lifecycle == "live"
    assert row.parked is False
    assert row.activity_at == datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
    assert row.claimed_items == ("YOK-2571",), "only item claims are holdings"


def test_session_rows_are_empty_for_an_envelope_without_rows() -> None:
    assert session_rows({"fields": []}) == {}


def test_a_parked_session_and_an_ended_session_are_distinct_facts() -> None:
    result = {
        "rows": [
            {"session_id": "p", "mode": "parked", "quiet_reason": "waiting"},
            {"session_id": "e", "ended_at": "2026-08-28T16:00:00Z"},
            {
                "session_id": "t",
                "ended_at": "2026-08-28T16:00:00Z",
                "terminated_at": "2026-08-28T16:00:00Z",
            },
        ]
    }
    rows = session_rows(result)
    assert rows["p"].parked is True and rows["p"].lifecycle == "live"
    assert rows["e"].lifecycle == "ended"
    assert rows["t"].lifecycle == "terminated"


def test_item_rows_union_the_three_scheduler_buckets() -> None:
    """Ranked, blocked, and frozen together are the in-flight set."""
    result = {
        "ranked_steps": [
            {
                "item_id": "YOK-1",
                "status": "implementing",
                "title": "t",
                "claim_state": "claimed_by_other_live",
                "project": "yoke",
            }
        ],
        "blocked_steps": [{"item_id": "YOK-2", "status": "idea"}],
        "frozen_steps": [{"item_id": "YOK-3", "status": "planning"}],
        "selected_step": {"item_id": "YOK-99", "status": "implementing"},
    }
    rows = item_rows(result)
    assert sorted(rows) == ["YOK-1", "YOK-2", "YOK-3"]
    assert rows["YOK-1"].unclaimed is False
    assert rows["YOK-2"].claim_state == "unknown"
    assert "YOK-99" not in rows, "selected_step repeats a ranked entry"


def test_envelope_rows_flatten_one_row_per_recipient() -> None:
    result = {
        "count": 1,
        "messages": [
            {
                "message_id": "de0fcd51-a4ad-4a92-9b05-4f98203eb4ec",
                "sender_session_id": "19c69dca-39fd-44d8-8f1a-3dcdb172eaa7",
                "created_at": "2026-08-28T16:32:05Z",
                "recipients": [
                    {
                        "session_id": "a",
                        "state": "pending",
                        "injection_count": 0,
                        "created_at": "2026-08-28T16:32:49Z",
                    },
                    {
                        "session_id": "b",
                        "state": "acknowledged",
                        "injection_count": 4,
                    },
                ],
            }
        ],
    }
    rows = envelope_rows(result)
    assert len(rows) == 2
    first = rows[("de0fcd51-a4ad-4a92-9b05-4f98203eb4ec", "a")]
    assert first.state == "pending"
    assert first.injection_count == 0
    assert first.created_at == datetime(2026, 8, 28, 16, 32, 49, tzinfo=timezone.utc)
    second = rows[("de0fcd51-a4ad-4a92-9b05-4f98203eb4ec", "b")]
    assert second.created_at == datetime(2026, 8, 28, 16, 32, 5, tzinfo=timezone.utc), (
        "a recipient without its own timestamp falls back to the message's"
    )


def test_envelope_rows_are_empty_for_an_envelope_without_messages() -> None:
    assert envelope_rows({"count": 0}) == {}


def test_timestamps_normalize_to_utc_and_tolerate_absence() -> None:
    assert parse_timestamp("2026-08-28T17:00:00Z") == datetime(
        2026, 8, 28, 17, 0, tzinfo=timezone.utc
    )
    assert parse_timestamp("2026-08-28T19:00:00+02:00") == datetime(
        2026, 8, 28, 17, 0, tzinfo=timezone.utc
    )
    assert parse_timestamp("2026-08-28T17:00:00") == datetime(
        2026, 8, 28, 17, 0, tzinfo=timezone.utc
    )
    for absent in (None, "", "   ", "not-a-timestamp", 17):
        assert parse_timestamp(absent) is None
