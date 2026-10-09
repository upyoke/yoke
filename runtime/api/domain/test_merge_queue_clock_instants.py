"""Native queue clocks and immutable notice keys share exact instant identity."""

from dataclasses import replace
from datetime import timedelta

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    DIRTY,
    MERGED,
    OUT_OF_QUEUE,
    ejected_message_id,
    inject,
    message_count,
    observe,
    observer_connection,
)
from runtime.api.domain.test_merge_queue_landing_record import _record
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import merge_queue_landing_observer as observer
from yoke_core.domain.merge_queue_landing_notice import arming_notice_key
from yoke_core.domain.merge_queue_landing_record import (
    read_landing_record,
    record_from_payload,
    write_landing_record,
)
from yoke_core.domain.merge_queue_landing_record_state import PENDING
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.merge_queue_landing_record_schema import (
    ensure_merge_queue_landing_record_schema,
)

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


@pytest.mark.parametrize("zone", ZONES)
def test_native_queue_refresh_preserves_semantic_change_microseconds(test_db, zone):
    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    ensure_merge_queue_landing_record_schema(test_db)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    record = replace(_record(PENDING, MOMENT, narrative="Queued"), item_id=7)
    write_landing_record(test_db, record)
    later = MOMENT + timedelta(microseconds=1)
    write_landing_record(test_db, replace(record, observed_at=later, changed_at=later))
    observed = read_landing_record(test_db, 7)
    assert observed.observed_at == later
    assert observed.changed_at == MOMENT
    payload = observed.payload()
    assert payload["observed_at"] == format_instant(later)
    assert payload["changed_at"] == format_instant(MOMENT)
    public = record_from_payload(payload, expected_public_ref=f"CLK-{7}")
    assert public.observed_at == later
    assert public.changed_at == MOMENT
    write_landing_record(
        test_db, replace(observed, narrative="Changed", changed_at=later)
    )
    assert read_landing_record(test_db, 7).changed_at == later


@pytest.mark.parametrize("zone", ZONES)
def test_observer_landing_and_notification_bind_native_microseconds(
    test_db, monkeypatch, zone
):
    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    ensure_merge_queue_landing_record_schema(test_db)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    test_db.execute("UPDATE items SET merge_queue_pr_number='42' WHERE id=7")
    test_db.commit()
    monkeypatch.setattr(observer, "push_notice", lambda *_args, **_kwargs: "delivered")
    current = MOMENT + timedelta(microseconds=1)
    result = observer.observe_pending_landings(
        test_db,
        [1],
        now=current,
        read_state=lambda *_args: (
            replace(MERGED, merged_at=format_instant(MOMENT)),
            None,
        ),
        cadence_seconds=0,
    )
    assert result["landed"] == result["notified"] == 1
    row = test_db.execute(
        "SELECT merged_at,merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=7"
    ).fetchone()
    assert tuple(row) == (MOMENT, MOMENT, current)
    assert read_landing_record(test_db, 7).observed_at == current


@pytest.mark.parametrize(
    "value",
    ["", "2026-10-09T10:11:12", "2026-02-30T10:11:12Z", 0, MOMENT.replace(tzinfo=None)],
)
def test_declared_observation_clock_refuses_before_sql(value):
    with pytest.raises((TypeError, ValueError)):
        _record(PENDING, value, narrative="Clock refusal")
    with pytest.raises((TypeError, ValueError)):
        observer.observe_pending_landings(object(), [1], now=value)


def test_unknown_public_clock_stays_null_and_cannot_be_written():
    record = _record(PENDING, None, narrative="Unknown clock")
    assert record.payload()["observed_at"] is None
    assert (
        record_from_payload(
            record.payload(), expected_public_ref=f"CLK-{7}"
        ).observed_at
        is None
    )
    with pytest.raises((TypeError, ValueError)):
        write_landing_record(object(), record)


def test_legacy_arming_key_and_receipt_bytes_survive_qualified_offset_reuse():
    conn = observer_connection()
    try:
        observe(conn)
        message_id = ejected_message_id(conn)
        key = conn.execute(
            "SELECT idempotency_key FROM session_messages WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        prefix = key.rsplit(":armed:", 1)[0]
        legacy = prefix + ":armed:2026-08-27T22:45:00+05:45"
        conn.execute(
            "UPDATE session_messages SET idempotency_key=? WHERE message_id=?",
            (legacy, message_id),
        )
        conn.commit()
        before = tuple(
            conn.execute(
                "SELECT body,body_sha256,selector_snapshot,idempotency_key FROM session_messages WHERE message_id=?",
                (message_id,),
            ).fetchone()
        )
        episode = parse_instant("2026-08-27T17:00:00Z")
        assert arming_notice_key(conn, head_key=prefix, enqueued_at=episode) == legacy
        assert (
            arming_notice_key(
                conn, head_key=prefix, enqueued_at=episode + timedelta(microseconds=1)
            )
            == prefix + ":armed:2026-08-27T17:00:00.000001Z"
        )
        inject(conn, message_id)
        assert observe(conn)["ejected"] == 1
        assert message_count(conn) == 1
        after = tuple(
            conn.execute(
                "SELECT body,body_sha256,selector_snapshot,idempotency_key FROM session_messages WHERE message_id=?",
                (message_id,),
            ).fetchone()
        )
        assert after == before
        assert (
            conn.execute(
                "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
            ).fetchone()[0]
            is None
        )
    finally:
        conn.close()


def test_invalid_stored_arming_suffix_refuses_without_creating_a_new_identity():
    conn = observer_connection()
    try:
        observe(conn)
        message_id = ejected_message_id(conn)
        key = conn.execute(
            "SELECT idempotency_key FROM session_messages WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        prefix = key.rsplit(":armed:", 1)[0]
        conn.execute(
            "UPDATE session_messages SET idempotency_key=? WHERE message_id=?",
            (prefix + ":armed:unknown-clock", message_id),
        )
        with pytest.raises(ValueError, match="invalid stored arming notice clock"):
            arming_notice_key(conn, head_key=prefix, enqueued_at=MOMENT)
        assert message_count(conn) == 1
    finally:
        conn.close()


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("rearmed", [False, True])
def test_native_ejection_clears_only_its_exact_arming_instant(
    test_db, monkeypatch, zone, rearmed
):
    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    ensure_merge_queue_landing_record_schema(test_db)
    create_session_control_tables(test_db)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    test_db.execute(
        "UPDATE items SET merge_queue_pr_number='42',merge_queue_enqueued_at=%s WHERE id=7",
        (MOMENT,),
    )
    test_db.commit()
    next_episode = MOMENT + timedelta(microseconds=1)

    def delivered(conn, **_kwargs):
        if rearmed:
            conn.execute(
                "UPDATE items SET merge_queue_enqueued_at=%s WHERE id=7",
                (next_episode,),
            )
        return "delivered"

    monkeypatch.setattr(observer, "push_notice", delivered)
    result = observer.observe_pending_landings(
        test_db,
        [1],
        now=MOMENT + timedelta(seconds=1),
        read_state=lambda *_args: (DIRTY, None),
        read_membership=lambda *_args: (OUT_OF_QUEUE, None),
        read_checks=lambda *_args: ((), None),
        cadence_seconds=0,
    )
    assert result["ejected"] == 1
    clock = test_db.execute(
        "SELECT merge_queue_enqueued_at FROM items WHERE id=7"
    ).fetchone()[0]
    assert clock == (next_episode if rearmed else None)


@pytest.mark.parametrize(
    "clock",
    [
        "2026-10-09T10:11:12.345678Z",
        "2026-10-09T15:56:12.345678+05:45",
        None,
    ],
)
def test_landing_models_format_only_report_clock_owners(clock):
    import json
    from yoke_core.domain.merge_queue_hold import _landed
    from yoke_core.domain.merge_queue_readiness import classify_readiness
    from yoke_core.engines.merge_worktree_pr_queue import PrLandingState

    state = PrLandingState(
        True, True, False, merged_at=clock, merge_commit_sha="opaque"
    )
    expected = MOMENT if clock is not None else None
    readiness = classify_readiness(
        pr_number="42", target="main", state=state, members=[]
    )
    hold = _landed(readiness, outcome="landed", actions=(), before=readiness)
    assert state.merged_at == readiness.merged_at == hold.merged_at == expected
    wire = format_instant(MOMENT) if clock is not None else None
    assert json.loads(json.dumps(readiness.to_dict()))["merged_at"] == wire
    payload = json.loads(json.dumps(hold.to_dict()))
    assert payload["merged_at"] == payload["before"]["merged_at"] == wire
    assert payload["merge_commit_sha"] == "opaque"
    if wire is not None:
        assert wire in payload["refusal"]


@pytest.mark.parametrize(
    "clock", ["", "2026-10-09", "2026-10-09T10:11:12", "2026-10-09T10:11:12-00:00"]
)
def test_landing_model_constructor_refuses_unverifiable_clock(clock):
    from yoke_core.engines.merge_worktree_pr_queue import PrLandingState

    with pytest.raises(InvalidInstant):
        PrLandingState(True, True, False, merged_at=clock)


@pytest.mark.parametrize(
    "clock", ["2026-10-09", "2026-10-09T10:11:12", "2026-10-09T10:11:12-00:00"]
)
def test_graphql_landing_clock_refusal_is_unreadable(monkeypatch, clock):
    from types import SimpleNamespace
    from yoke_core.engines import merge_worktree_pr_check_runs as checks

    monkeypatch.setattr(
        checks,
        "resolve_auth_detail",
        lambda *_args: (SimpleNamespace(repo="owner/repo", token="opaque"), None),
    )
    monkeypatch.setattr(
        checks,
        "graphql_with_auth",
        lambda *_args, **_kw: (
            {
                "repository": {"pullRequest": {"merged": True, "mergedAt": clock}},
            },
            None,
        ),
    )
    projection = checks.read_pr_landing_and_required_checks(object(), "42")
    assert projection.state is None
    assert projection.required_checks is None
    assert "clock" in projection.state_error
    assert projection.state_error == projection.checks_error
