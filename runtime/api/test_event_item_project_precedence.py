"""Every write gateway prefers an item's durable project over its session."""

import json
import pytest
from runtime.api import test_event_write_path_project_attribution as support
from yoke_core.domain.events import emit_event
from yoke_core.domain.events_writes import cmd_insert
from yoke_core.domain.db_helpers import connect


@pytest.fixture
def events_db(tmp_path, monkeypatch):
    yield from support.events_db.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize("writer", ["native", "raw"])
@pytest.mark.parametrize("context", [None, {"project_id": support.YOKE_ID}])
def test_item_project_precedes_session_and_context_precedes_item(
    events_db, writer, context
):
    session = "item-owner-probe"
    support._seed_session(
        events_db, session, executor="codex", project_id=support.YOKE_ID
    )
    with connect(events_db) as conn:
        row = conn.execute(
            "SELECT id FROM items WHERE project_id=%s LIMIT 1", (support.EXTERNAL_ID,)
        ).fetchone()
        if row is None:
            from runtime.api.conftest import insert_item

            insert_item(conn, id=8181, project_id=support.EXTERNAL_ID)
            conn.commit()
            item = 8181
        else:
            item = int(row[0])
    if writer == "native":
        result = emit_event(
            "ItemOwnerProbe",
            event_kind="system",
            event_type="test",
            session_id=session,
            item_id=str(item),
            context=context,
        )
        assert result.ok
        event = result.event_id
    else:
        event = "item-owner-probe-event"
        assert cmd_insert(
            event_id=event,
            source_type="system",
            session_id=session,
            event_kind="system",
            event_type="test",
            event_name="ItemOwnerProbe",
            item_id=str(item),
            envelope=json.dumps({"context": context}),
            skip_severity=True,
        )
    expected = support.YOKE_ID if context else support.EXTERNAL_ID
    assert support._project_id(events_db, event) == expected
