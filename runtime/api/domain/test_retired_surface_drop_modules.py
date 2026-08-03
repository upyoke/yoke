"""Drop modules converge installs that still carry retired surfaces.

A freshly born universe never has the legacy path-claim identity columns or
the retired session-report table, while an install that predates the drops
still does. Each module must remove the surface where present and succeed as
a no-op where the install was born clean, so one packaged manifest can run
across every environment and tenant regardless of birth date.
"""

from __future__ import annotations

from yoke_core.domain.migrations.drop_wrapup_reports import (
    apply as wrapup_apply,
    invariants as wrapup_verify,
)
from yoke_core.domain.migrations.path_claims_typed_owner_cleanup import (
    apply as typed_owner_apply,
    invariants as typed_owner_verify,
)

LEGACY_PATH_CLAIM_COLUMNS = (
    ("actor_id", "TEXT"),
    ("item_id", "INTEGER"),
    ("session_id", "TEXT"),
    ("work_claim_id", "INTEGER"),
)


def _column_names(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {row["column_name"] for row in rows}


def _add_legacy_path_claim_columns(conn) -> None:
    for column, type_name in LEGACY_PATH_CLAIM_COLUMNS:
        conn.execute(
            f'ALTER TABLE path_claims ADD COLUMN "{column}" {type_name}'
        )
    conn.commit()


def test_typed_owner_cleanup_drops_legacy_columns(test_db):
    _add_legacy_path_claim_columns(test_db)
    assert {"actor_id", "session_id"} <= _column_names(test_db, "path_claims")

    typed_owner_apply(test_db)
    typed_owner_verify(test_db)

    remaining = _column_names(test_db, "path_claims")
    assert not {c for c, _ in LEGACY_PATH_CLAIM_COLUMNS} & remaining
    assert {"owner_kind", "owner_item_id", "owner_session_id"} <= remaining


def test_typed_owner_cleanup_is_noop_on_clean_install(test_db):
    before = _column_names(test_db, "path_claims")
    typed_owner_apply(test_db)
    typed_owner_verify(test_db)
    assert _column_names(test_db, "path_claims") == before


def test_wrapup_reports_drop_removes_stale_table(test_db):
    test_db.execute(
        'CREATE TABLE "wrapup_reports" (id INTEGER PRIMARY KEY, body TEXT)'
    )
    test_db.execute("INSERT INTO wrapup_reports (id, body) VALUES (1, 'stale')")
    test_db.commit()

    wrapup_apply(test_db)
    wrapup_verify(test_db)


def test_wrapup_reports_drop_is_noop_when_absent(test_db):
    wrapup_apply(test_db)
    wrapup_verify(test_db)
