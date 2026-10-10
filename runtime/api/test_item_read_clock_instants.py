"""Item read owners distinguish native JSON facts from textual clock cells."""

from datetime import datetime

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.items_projection import ITEM_INSTANT_FIELDS
from yoke_core.domain.project_identity import item_project_join_select

STAMP = parse_instant("1970-01-01T05:44:59.999999+05:45")
TITLE = "opaque 1969-12-31T23:59:59 clock-like title"


class _KeepOpen:
    def __init__(self, conn):
        self._conn = conn
        self.writes = []

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        self.writes.append((sql, params))
        return self._conn.execute(sql, params)

    def close(self):
        pass


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_real_item_clock_selectors_scalar_pipe_and_json_owners(
    test_db, monkeypatch, capsys, zone
):
    from runtime.api.fixtures.backlog import insert_item
    from runtime.api.domain.handlers.items_read_test_support import (
        insert_prefixed_project,
        insert_shared_slug_items,
        request_for,
    )
    from yoke_core.api import service_client_items_read, service_client_items_listing
    from yoke_core.api.service_client_items_parsing import _QI_ALL_FIELDS
    from yoke_core.domain import db_helpers, items_queries
    from yoke_core.domain.handlers import items_listing
    from yoke_core.domain.items_constants import CANONICAL_COLUMNS, LIST_COLUMNS
    from yoke_core.domain.project_identity import render_item_ref

    fields = sorted(ITEM_INSTANT_FIELDS)
    expected = {
        field: STAMP
        if field
        in {"created_at", "updated_at", "spec_updated_at", "merge_queue_enqueued_at"}
        else None
        for field in fields
    }
    conn = _KeepOpen(test_db)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    insert_item(test_db, id=17, title=TITLE, created_at=STAMP, updated_at=STAMP)
    test_db.execute(
        "UPDATE items SET "
        + ",".join(field + "=%s" for field in fields)
        + " WHERE id=%s",
        (*expected.values(), 17),
    )
    test_db.commit()
    public_ref = render_item_ref(test_db, 17)
    monkeypatch.setattr(items_queries, "connect", lambda *_args: conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *_args: conn)
    monkeypatch.setattr(service_client_items_read, "_get_db_readonly", lambda: conn)
    monkeypatch.setattr(service_client_items_listing, "_get_db_readonly", lambda: conn)
    exposed = sorted(ITEM_INSTANT_FIELDS & _QI_ALL_FIELDS)
    assert {"created_at", "updated_at", "merged_at"} <= set(exposed)
    text = {
        field: "" if value is None else format_instant(value)
        for field, value in expected.items()
    }
    for style in ("ISO, MDY", "SQL, DMY"):
        test_db.execute("SELECT set_config('DateStyle',%s,false)", (style,))
        assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
        columns, joined = item_project_join_select(fields)
        assert not joined
        row = test_db.execute(
            "SELECT " + columns + " FROM items i WHERE id=17"
        ).fetchone()
        assert list(row) == list(text.values())
        for field in fields:
            assert items_queries.query_item(17, field) == text[field]
        for field in exposed:
            assert service_client_items_read.cmd_item_get([public_ref, field]) == 0
            assert capsys.readouterr().out == (
                text[field] + "\n" if text[field] else ""
            )

    assert items_queries.query_item(17, "title") == TITLE
    assert items_queries.query_item(17, "frozen") == "false"
    assert items_queries.query_item(17, "spec") == ""

    test_db.execute("SELECT set_config('DateStyle','ISO, MDY',false)")
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    columns, _ = item_project_join_select(fields, native_instants=True)
    row = test_db.execute("SELECT " + columns + " FROM items i WHERE id=17").fetchone()
    assert list(row) == list(expected.values())
    assert all(value is None or isinstance(value, datetime) for value in row)
    for columns, rendered in (
        (CANONICAL_COLUMNS, items_queries.query_item_row(17)),
        (LIST_COLUMNS, items_queries.query_items_list()),
    ):
        values = rendered.split("|")
        for field in fields:
            if field in columns:
                assert values[columns.index(field)] == text[field]
        assert values[columns.index("title")] == TITLE
    assert (
        service_client_items_listing.cmd_item_list(["--fields", ",".join(exposed)]) == 0
    )
    assert capsys.readouterr().out.strip("\n").split("|") == [
        text[field] for field in exposed
    ]
    outcome = items_listing.handle_items_list(
        request_for("items.list.run", {"fields": ["title", *exposed]})
    )
    assert outcome.primary_success
    native = outcome.result_payload["rows"][0]
    assert native == {"title": TITLE, **{field: expected[field] for field in exposed}}
    assert all(
        native[field] is None or isinstance(native[field], datetime)
        for field in exposed
    )
    wire = FunctionCallResponse(
        function="items.list.run",
        version="v1",
        success=True,
        result=outcome.result_payload,
    ).model_dump(mode="json")
    assert wire["result"]["rows"] == [
        {
            "title": TITLE,
            **{
                field: None if expected[field] is None else text[field]
                for field in exposed
            },
        }
    ]

    # Shared visibility fixtures own actual SQL parameters, including project clocks.
    insert_prefixed_project(conn, project_id=112, prefix="EXAMPLE")
    insert_shared_slug_items(conn)
    stamp = parse_instant("2026-01-01T00:00:00Z")
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    fixture_rows = test_db.execute(
        "SELECT created_at FROM projects WHERE id IN (110,111,112)"
    ).fetchall()
    assert [row[0] for row in fixture_rows] == [stamp] * 3
    fixture_writes = [
        (sql, params)
        for sql, params in conn.writes
        if sql.startswith(("INSERT INTO projects ", "INSERT INTO organizations "))
    ]
    assert len(fixture_writes) == 3
    for _, params in fixture_writes:
        assert any(isinstance(value, datetime) and value == stamp for value in params)
