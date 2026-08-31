"""Durable-activity pairing for HC-event-family-liveness."""

from __future__ import annotations

import pytest

from runtime.api.conftest import (
    insert_event,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.engines._doctor_hc_db_full_test_helpers import _result, _run_hc
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.engines.doctor import hc_event_family_liveness
from yoke_core.engines.doctor_hc_db_events_emission import (
    EVENT_FAMILY_LIVENESS_PAIRS,
)


OLD_TIMESTAMP = "2000-01-01T00:00:00Z"


def _insert_family_activity(conn, table: str, timestamp: str) -> None:
    if table == "items":
        insert_item(conn, id=901, created_at=timestamp, updated_at=timestamp)
        return
    if table == "qa_requirements":
        insert_qa_requirement(conn, item_id=901, created_at=timestamp)
        return
    if table == "qa_runs":
        requirement = insert_qa_requirement(conn, item_id=901, created_at=OLD_TIMESTAMP)
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            created_at=timestamp,
            completed_at=timestamp,
        )
        return
    if table == "harness_sessions":
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, execution_lane, workspace, "
            "project_id, offered_at, last_heartbeat) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "sess-event-family",
                "codex",
                "openai",
                "test-model",
                "primary",
                "/tmp",
                1,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
        return
    raise AssertionError(f"unhandled durable family {table}")


def test_passes_when_no_declared_family_has_recent_activity(test_db) -> None:
    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "PASS"
    assert "0 had recent durable activity" in result.detail


@pytest.mark.parametrize(
    "pair",
    EVENT_FAMILY_LIVENESS_PAIRS,
    ids=lambda pair: pair.durable_table,
)
def test_warns_when_recent_durable_activity_has_no_matching_event(
    test_db, pair
) -> None:
    _insert_family_activity(test_db, pair.durable_table, iso8601_now())

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "WARN"
    assert pair.durable_table in result.detail
    assert pair.expected_event in result.detail


@pytest.mark.parametrize(
    "pair",
    EVENT_FAMILY_LIVENESS_PAIRS,
    ids=lambda pair: pair.durable_table,
)
def test_passes_when_recent_activity_has_its_expected_event(test_db, pair) -> None:
    timestamp = iso8601_now()
    _insert_family_activity(test_db, pair.durable_table, timestamp)
    insert_event(
        test_db,
        event_id=f"event-{pair.durable_table}",
        event_name=pair.expected_event,
        created_at=timestamp,
    )

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "PASS"


def test_rare_family_without_activity_does_not_warn(test_db) -> None:
    _insert_family_activity(test_db, "qa_requirements", OLD_TIMESTAMP)

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "PASS"
