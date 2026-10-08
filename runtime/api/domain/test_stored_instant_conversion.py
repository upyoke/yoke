"""Historical native conversion preserves instants, guards and atomic refusal."""

from datetime import datetime, timezone

import pytest

from yoke_core.domain import db_helpers, stored_instant_conversion as conversion


_TABLE = "instant_conversion_fixture"
_ROSTER = tuple(
    (_TABLE, name)
    for name in ("created_at", "updated_at", "observed_at", "expires_at", "optional_at")
)


def _fixture(conn, monkeypatch, *, native_creation=False):
    monkeypatch.setattr(
        conversion,
        "_OWNER_CREATION_REPAIRS",
        {(_TABLE, "updated_at"), (_TABLE, "observed_at")},
    )
    monkeypatch.setattr(conversion, "_EPOCH_SECONDS", {(_TABLE, "expires_at")})
    creation_type = "timestamptz" if native_creation else "text"
    conn.execute(
        f"CREATE TABLE {_TABLE} (id INTEGER PRIMARY KEY, "
        f"created_at {creation_type} NOT NULL, updated_at text NOT NULL, "
        "observed_at text NOT NULL, expires_at bigint, optional_at text DEFAULT '')"
    )
    conn.execute(f"CREATE INDEX fixture_creation_index ON {_TABLE}(created_at,id)")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_conversion_is_native_and_independent_of_session_zone(
    test_db, monkeypatch, zone
):
    with db_helpers.connect() as conn:
        _fixture(conn, monkeypatch)
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (%s,%s,%s,%s,%s,%s)",
            (1, "2026-10-08T12:30:00.123456-04:00", "", "--agent", 1, ""),
        )
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (%s,%s,%s,%s,%s,%s)",
            (2, "2026-10-08 16:30:00.654321", "2026-10-08", "2026-10-08", None, None),
        )
        conn.commit()
        conn.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
        conversion.convert_stored_instants(conn, _ROSTER)
        conversion.assert_native_stored_instants(conn, _ROSTER)
        conversion.convert_stored_instants(conn, _ROSTER)
        conn.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
        first, second = conn.execute(f"SELECT * FROM {_TABLE} ORDER BY id").fetchall()
        expected = datetime(2026, 10, 8, 16, 30, 0, 123456, timezone.utc)
        assert first[1:4] == (expected,) * 3
        assert first[4] == datetime(1970, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        assert first[5] is None
        assert second[1] == datetime(2026, 10, 8, 16, 30, 0, 654321, timezone.utc)
        assert second[2:4] == (datetime(2026, 10, 8, tzinfo=timezone.utc),) * 2
        assert second[4:] == (None, None)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM pg_indexes WHERE tablename=%s AND indexname=%s",
                (_TABLE, "fixture_creation_index"),
            ).fetchone()[0]
            == 1
        )
        # The empty-string default is removed rather than retained on a native field.
        assert (
            conn.execute(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name=%s AND column_name='optional_at'",
                (_TABLE,),
            ).fetchone()[0]
            is None
        )


def test_owner_creation_can_already_be_native(test_db, monkeypatch):
    with db_helpers.connect() as conn:
        _fixture(conn, monkeypatch, native_creation=True)
        expected = datetime(2026, 10, 8, 16, 30, 0, 123456, timezone.utc)
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (%s,%s,%s,%s,%s,%s)",
            (1, expected, "", "--agent", None, None),
        )
        conversion.convert_stored_instants(conn, _ROSTER)
        assert conn.execute(
            f"SELECT updated_at,observed_at FROM {_TABLE}"
        ).fetchone() == (expected, expected)


def test_refusal_precedes_type_changes_and_preserves_original_values(
    test_db, monkeypatch
):
    with db_helpers.connect() as conn:
        _fixture(conn, monkeypatch)
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (%s,%s,%s,%s,%s,%s)",
            (1, "broken creation", "", "--agent", None, None),
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="instant_historical_repair_unresolved"):
            conversion.convert_stored_instants(conn, _ROSTER)
        assert (
            conn.execute(f"SELECT created_at FROM {_TABLE}").fetchone()[0]
            == "broken creation"
        )
        assert (
            conn.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name=%s AND column_name='created_at'",
                (_TABLE,),
            ).fetchone()[0]
            == "text"
        )


def test_type_rewrite_preserves_append_only_guards(test_db, monkeypatch):
    with db_helpers.connect() as conn:
        _fixture(conn, monkeypatch)
        conn.execute(
            f"INSERT INTO {_TABLE} VALUES (1,'2026-10-08T16:30:00Z',"
            "'2026-10-08T16:30:00Z','2026-10-08T16:30:00Z',NULL,NULL)"
        )
        conn.execute(
            "CREATE FUNCTION reject_fixture_edit() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RAISE EXCEPTION 'fixture is append-only'; END $$"
        )
        conn.execute(
            f"CREATE TRIGGER fixture_edit_guard BEFORE UPDATE OR DELETE ON {_TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION reject_fixture_edit()"
        )
        conversion.convert_stored_instants(conn, _ROSTER)
        conn.commit()
        assert (
            conn.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgname='fixture_edit_guard'"
            ).fetchone()[0]
            == "O"
        )
        with pytest.raises(Exception, match="fixture is append-only"):
            conn.execute(f"UPDATE {_TABLE} SET observed_at=now()")
        conn.rollback()


def test_unclassified_integer_unit_refuses_before_ddl(test_db, monkeypatch):
    with db_helpers.connect() as conn:
        _fixture(conn, monkeypatch)
        monkeypatch.setattr(conversion, "_EPOCH_SECONDS", set())
        with pytest.raises(RuntimeError, match="instant_epoch_unit_undeclared"):
            conversion.convert_stored_instants(conn, _ROSTER)
