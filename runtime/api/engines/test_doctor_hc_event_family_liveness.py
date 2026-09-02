"""Durable-activity pairing for HC-event-family-liveness."""

from __future__ import annotations

import json

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
from yoke_core.engines.doctor_event_family_pairing import (
    EVENT_FAMILY_LIVENESS_PAIRS,
)


OLD_TIMESTAMP = "2000-01-01T00:00:00Z"


def _paired_envelope(row_id_key: str, row_id: int) -> str:
    """The envelope shape per-row pairing reads the durable row id from."""
    return json.dumps({"context": {"detail": {row_id_key: int(row_id)}}})


def _insert_family_activity(conn, table: str, timestamp: str) -> int | None:
    """Insert one recent row for *table*, returning its id where pairing needs it."""
    if table == "items":
        insert_item(conn, id=901, created_at=timestamp, updated_at=timestamp)
        return 901
    if table == "qa_requirements":
        row = insert_qa_requirement(conn, item_id=901, created_at=timestamp)
        return int(row["id"])
    if table == "qa_runs":
        requirement = insert_qa_requirement(conn, item_id=901, created_at=OLD_TIMESTAMP)
        run = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            created_at=timestamp,
            completed_at=timestamp,
        )
        return int(run["id"])
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
        return None
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
    row_id = _insert_family_activity(test_db, pair.durable_table, timestamp)
    envelope = (
        _paired_envelope(pair.event_row_id_key, row_id)
        if pair.event_row_id_key
        else None
    )
    insert_event(
        test_db,
        event_id=f"event-{pair.durable_table}",
        event_name=pair.expected_event,
        created_at=timestamp,
        envelope=envelope,
    )

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "PASS"


def test_one_emitting_write_path_does_not_mask_a_silent_sibling(test_db) -> None:
    """The regression: a live path answered for a silent path sharing the table."""
    timestamp = iso8601_now()
    emitting = insert_qa_requirement(
        test_db, item_id=901, created_at=timestamp, requirement_source="explicit"
    )
    insert_event(
        test_db,
        event_id="event-explicit-requirement",
        event_name="QARequirementCreated",
        created_at=timestamp,
        envelope=_paired_envelope("requirement_id", int(emitting["id"])),
    )
    insert_qa_requirement(
        test_db, item_id=901, created_at=timestamp, requirement_source="flow_derived"
    )

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "WARN"
    assert "requirement_source=flow_derived" in result.detail
    assert "1 unpaired" in result.detail
    assert "requirement_source=explicit" not in result.detail


def test_rare_family_without_activity_does_not_warn(test_db) -> None:
    _insert_family_activity(test_db, "qa_requirements", OLD_TIMESTAMP)

    result = _result(_run_hc(hc_event_family_liveness, test_db))

    assert result.result == "PASS"
