"""Cursor paging, compact projection, and scope for the Events history shape."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.events_history_read import HISTORY_FIELDS
from yoke_core.domain.handlers import events_reads
from runtime.api.conftest import insert_event


STAMP = "2026-09-08T03:00:00Z"


def _request(payload=None, *, actor_id: str | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="events.query.run",
        actor=ActorContext(actor_id=actor_id, session_id="s-caller"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _history(payload=None, *, actor_id: str | None = None):
    body = {"history": {"limit": 2}, **(payload or {})}
    return events_reads.handle_events_query(_request(body, actor_id=actor_id))


def _seed(conn, count: int, *, created_at: str = STAMP, **kwargs) -> None:
    for index in range(count):
        insert_event(
            conn,
            event_id=f"evt-{index}",
            event_name=f"Event{index}",
            created_at=created_at,
            **kwargs,
        )


def test_history_returns_only_the_rendered_facts_and_never_the_envelope(test_db):
    insert_event(
        test_db,
        event_id="evt-shape",
        event_name="StatusChanged",
        event_kind="lifecycle",
        event_type="status",
        created_at=STAMP,
        envelope='{"context": {"from_status": "idea", "to_status": "implementing"}}',
    )

    result = _history().result_payload

    assert result["fields"] == list(HISTORY_FIELDS)
    row = result["rows"][0]
    assert set(row) == set(HISTORY_FIELDS)
    # Derived server-side from the envelope, which is then dropped: the
    # timeline shows this label and never the stored text behind it.
    assert row["context_label"] == "idea → implementing"
    assert row["category"] == "workflow"
    for dropped in ("envelope", "id", "event_id", "session_id", "trace_id"):
        assert dropped not in row


def test_history_pages_by_cursor_without_gaps_or_duplicates(test_db):
    _seed(test_db, 5)

    first = _history().result_payload
    second = _history({"history": {"limit": 2, "cursor": first["next_cursor"]}})
    second = second.result_payload
    third = _history({"history": {"limit": 2, "cursor": second["next_cursor"]}})
    third = third.result_payload

    names = [
        row["event_name"] for page in (first, second, third) for row in page["rows"]
    ]
    # Every stamp is identical, so only the tie-break in the cursor keeps the
    # walk moving; a page boundary that ignored it would repeat rows forever.
    assert names == ["Event4", "Event3", "Event2", "Event1", "Event0"]
    assert len(set(names)) == len(names)
    assert third["next_cursor"] is None


def test_history_orders_by_time_then_id(test_db):
    insert_event(
        test_db,
        event_id="evt-old",
        event_name="Older",
        created_at="2026-09-08T01:00:00Z",
    )
    insert_event(
        test_db,
        event_id="evt-new",
        event_name="Newer",
        created_at="2026-09-08T04:00:00Z",
    )
    _seed(test_db, 2)

    result = _history({"history": {"limit": 10}}).result_payload

    assert [row["event_name"] for row in result["rows"]] == [
        "Newer",
        "Event1",
        "Event0",
        "Older",
    ]


def test_filters_apply_before_the_page_is_cut(test_db):
    _seed(test_db, 3, severity="INFO")
    insert_event(
        test_db,
        event_id="evt-red",
        event_name="ItFailed",
        severity="ERROR",
        created_at="2026-09-08T01:00:00Z",
    )

    result = _history(
        {
            "min_severity": "ERROR",
            "history": {"limit": 2},
        }
    ).result_payload

    # The one match is older than the whole first unfiltered page. Filtering
    # after the limit would have returned nothing at all.
    assert [row["event_name"] for row in result["rows"]] == ["ItFailed"]
    assert result["next_cursor"] is None


def test_since_and_event_name_filters_narrow_the_history(test_db):
    insert_event(
        test_db,
        event_id="evt-ancient",
        event_name="Wanted",
        created_at="2020-01-01T00:00:00Z",
    )
    insert_event(test_db, event_id="evt-recent", event_name="Wanted", created_at=STAMP)
    insert_event(test_db, event_id="evt-other", event_name="Unwanted", created_at=STAMP)

    named = _history({"event_name": "Wanted", "history": {"limit": 10}})
    windowed = _history(
        {
            "event_name": "Wanted",
            "since": "2026-01-01T00:00:00Z",
            "history": {"limit": 10},
        }
    )

    assert len(named.result_payload["rows"]) == 2
    assert len(windowed.result_payload["rows"]) == 1


def test_malformed_cursor_is_refused_with_the_way_back(test_db):
    _seed(test_db, 1)

    outcome = _history({"history": {"limit": 2, "cursor": "not-a-cursor"}})

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "reload the first page" in outcome.error.message


def test_invalid_history_input_is_refused_by_name(test_db):
    outcome = _history({"history": {"limit": 5000}})

    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.history.limit"


def test_invisible_project_is_refused_rather_than_read_unscoped(test_db):
    from yoke_core.domain.actors import seed_human_actor

    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', %s)",
        ("2026-09-08T00:00:00Z",),
    )
    test_db.commit()
    actor_id = seed_human_actor(test_db)
    _seed(test_db, 1, project="yoke")
    insert_event(
        test_db,
        event_id="evt-other",
        event_name="Hidden",
        created_at=STAMP,
        project_id=77,
    )

    outcome = _history(
        {"project": "other", "history": {"limit": 10}},
        actor_id=str(actor_id),
    )

    assert not outcome.primary_success
    assert outcome.error.code == "permission_denied"
    assert "reload the first page" in outcome.error.message


def test_unscoped_history_stays_inside_the_actor_visible_projects(test_db):
    from yoke_core.domain.actors import seed_human_actor

    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', %s)",
        ("2026-09-08T00:00:00Z",),
    )
    test_db.commit()
    actor_id = seed_human_actor(test_db)
    insert_event(
        test_db,
        event_id="evt-hidden",
        event_name="Hidden",
        created_at=STAMP,
        project_id=77,
    )

    outcome = _history({"history": {"limit": 10}}, actor_id=str(actor_id))

    assert outcome.primary_success
    assert [row["event_name"] for row in outcome.result_payload["rows"]] == []


def test_history_page_is_a_fraction_of_the_raw_page_it_replaces(test_db):
    """The whole point of the shape: envelopes stop riding a rendered list."""
    import json

    envelope = json.dumps(
        {
            "context": {
                "function": "items.structured_field.replace",
                "result": "ok",
                "payload": {"field": "spec", "content": "x" * 2000},
            },
        }
    )
    for index in range(50):
        insert_event(
            test_db,
            event_id=f"evt-weight-{index}",
            event_name="YokeFunctionCalled",
            created_at=f"2026-09-08T03:{index:02d}:00Z",
            envelope=envelope,
        )

    compact = _history({"history": {"limit": 50}}).result_payload
    raw = events_reads.handle_events_query(_request({"limit": 50})).result_payload

    assert len(compact["rows"]) == len(raw["rows"]) == 50
    compact_bytes = len(json.dumps(compact["rows"]))
    raw_bytes = len(json.dumps(raw["rows"]))
    assert compact_bytes * 4 < raw_bytes, (compact_bytes, raw_bytes)


def test_query_without_history_keeps_the_existing_projection(test_db):
    insert_event(
        test_db,
        event_id="evt-legacy",
        event_name="StatusChanged",
        created_at=STAMP,
        envelope='{"context": {"from_status": "idea"}}',
    )

    outcome = events_reads.handle_events_query(_request({"limit": 5}))

    assert outcome.primary_success
    row = outcome.result_payload["rows"][0]
    assert row["envelope"]
    assert row["event_id"] == "evt-legacy"
    assert "next_cursor" not in outcome.result_payload
