"""Native keysets preserve microseconds, ties, nulls and opaque text keys."""

import base64
import json
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.deployment_run_history_read import (
    RunHistoryCursorError,
    decode_cursor as decode_run_cursor,
    read_deployment_run_history,
)
from yoke_core.domain.item_roster_order import RosterCursorError, decode_cursor
from yoke_core.domain.item_roster_read import read_item_roster
from yoke_core.domain.ouroboros_entries import cmd_insert_entry, get_entry_row
from yoke_core.domain.ouroboros_entry_roster import list_roster_page
from yoke_core.domain.ouroboros_roster_order import continuation


def _token(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_native_pages_preserve_exact_ties_and_nullable_review_order(
    test_db, monkeypatch, zone, direction
):
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    anchor = parse_instant("1969-12-31T23:59:59.999999Z")
    clocks = [
        anchor - timedelta(microseconds=1),
        anchor,
        anchor,
        anchor + timedelta(microseconds=1),
    ]
    entries = []
    for index, clock in enumerate(clocks):
        insert_item(test_db, id=1100 + index, title="native cursor", updated_at=clock)
        insert_deployment_run(
            test_db,
            id=f"native-run-{index}",
            flow="native-cursor-flow",
            status="succeeded",
            created_at=clock,
        )
        entry = int(
            cmd_insert_entry(
                test_db,
                clock,
                "tester",
                "opaque 1969-12-31",
                "native-cursor",
                str(index),
                "yoke",
            )
        )
        reviewed = None if index < 2 else clock
        test_db.execute(
            "UPDATE ouroboros_entries SET reviewed_at=%s WHERE id=%s", (reviewed, entry)
        )
        entries.append(entry)
    test_db.commit()
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    rows, cursor = [], None
    while True:
        page = read_item_roster(
            test_db,
            search="native cursor",
            page_size=1,
            cursor=cursor,
            sort_direction=direction,
        )
        rows.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        _, _, encoded, _ = json.loads(cursor)
        assert encoded == format_instant(rows[-1]["updated_at"])
    expected = list(range(1100, 1104))
    assert [row["internal_id"] for row in rows] == (
        expected if direction == "asc" else expected[::-1]
    )
    rows, cursor = [], None
    while True:
        page = read_deployment_run_history(
            test_db,
            project_ids=[1],
            search=None,
            status=None,
            environment=None,
            flow="native-cursor-flow",
            page_size=1,
            cursor=cursor,
            actor_id=None,
        )
        rows.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert decode_run_cursor(cursor) == (rows[-1]["created_at"], rows[-1]["id"])
    assert [row["id"] for row in rows] == [f"native-run-{i}" for i in [3, 2, 1, 0]]
    for column in ["timestamp", "reviewed_at"]:
        rows, cursor = [], None
        while True:
            page = list_roster_page(
                test_db,
                project="yoke",
                limit=1,
                category_prefix="native-cursor",
                sort={"column": column, "direction": direction},
                cursor=cursor,
            )
            rows.extend(page["entries"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
            payload = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            assert payload["value"] == rows[-1][column]
        assert [row["id"] for row in rows] == (
            entries if direction == "asc" else entries[::-1]
        )
        assert all(row["context"] == "opaque 1969-12-31" for row in rows)
    entry = get_entry_row(test_db, entries[0])
    assert entry["timestamp"] == format_instant(clocks[0])
    assert entry["reviewed_at"] is None
    assert entry["archived_at"] is None


@pytest.mark.parametrize(
    "bad", ["", "1969-12-31", "1969-12-31T23:59:59", "1969-12-31T23:59:59.0000001Z"]
)
def test_malformed_clock_cursors_refuse_instead_of_changing_the_bound(bad):
    with pytest.raises(RosterCursorError, match="Reload the Items page"):
        decode_cursor(json.dumps(["updated_at", "desc", bad, 1]))
    with pytest.raises(RunHistoryCursorError, match="Reload the first Runs page"):
        decode_run_cursor(_token({"created_at": bad, "run_id": "run"}))
    sort = {"column": "timestamp", "direction": "desc"}
    with pytest.raises(ValueError, match="Reload the Ouroboros page"):
        continuation(
            _token({"value": bad, "id": 1, "sort": sort, "projects": [1]}),
            sort,
            [1],
            conn=None,
        )


def test_sqlite_pages_use_canonical_clock_bounds(monkeypatch):
    from runtime.api.domain.test_deployment_run_history_read import _database, _read

    conn = _database()
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_history_read.present_deployment_runs",
        lambda _conn, rows, **_kwargs: rows,
    )
    first = _read(conn, page_size=1)
    second = _read(conn, page_size=1, cursor=first["next_cursor"])
    assert [row["id"] for row in first["rows"] if row["status"] == "failed"] == [
        "run-20260908-052"
    ]
    assert [row["id"] for row in second["rows"] if row["status"] == "succeeded"] == [
        "run-20260908-051"
    ]
    conn.close()


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_github_verification_orders_native_stamps_before_wire_projection(test_db, zone):
    from runtime.api.domain.handlers.capabilities_list_test_support import (
        insert_capability,
        insert_github_binding,
    )
    from yoke_core.domain.capabilities_list_read import list_capabilities

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    anchor = parse_instant("1969-12-31T23:59:59.999999Z")
    insert_capability(test_db, "github", verified_at=anchor - timedelta(microseconds=1))
    insert_github_binding(
        test_db,
        binding_verified_at=anchor,
        installation_verified_at="1970-01-01T05:30:00.000000+05:30",
    )
    row = list_capabilities()[0]
    assert row["verified_at"] == "1970-01-01T00:00:00.000000Z"
    assert row["verified_source"] == "repo-binding"
    assert row["state"] == "ready"


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_removed_custody_requires_a_strictly_later_native_creation(delta):
    from runtime.api.domain.test_deployment_run_removed_member_presentation import (
        Database,
        Rows,
        run,
    )
    from yoke_core.domain.deployment_run_member_presentation import removed_member_items

    anchor = parse_instant("1969-12-31T23:59:59.999999Z")

    class Custody(Database):
        def execute(self, sql, params):
            if "JOIN deployment_runs dr" in sql:
                return Rows(
                    [
                        {
                            "item_id": 7,
                            "id": "later",
                            "created_at": anchor + timedelta(microseconds=delta),
                        }
                    ]
                )
            return super().execute(sql, params)

    source = {**run(), "created_at": "1969-12-31T18:59:59.999999-05:00"}
    [member] = removed_member_items(Custody(), [source])["run-original"]
    assert member["later_run_id"] == ("later" if delta > 0 else None)
    assert member["removed_at"] is None
