"""Drop the in-app notification substrate and the nonblocking review kind.

Four producers filled these rows and none of them ever needed a person: a
strategy revision raised a review nobody acted on, and three notification
kinds fanned out event snapshots nobody read. The Inbox now carries only
what genuinely gates someone -- a decision request -- and messages, so the
delivery table, the review kind, and the ``blocking`` flag that once told
the two apart all go together.

The flag goes because it no longer distinguishes anything: the review kind
was the only nonblocking one, so every surviving request blocks by being a
request. ``ItemBlocked`` / ``ItemUnblocked`` / ``InboxNotificationRead``
were emitted only to feed these deliveries, so their registry rows are
retired with them; the deployment-run and decision-request events stay,
because the pipeline and the decision lifecycle read them.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import DECISION_REQUEST_KINDS
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)


#: A build older than this entry reads ``addressed_event_deliveries`` and the
#: ``blocking`` column on every Inbox render, so it cannot serve a database
#: this entry has converged.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

DELIVERY_TABLE = "addressed_event_deliveries"
DELIVERY_INDEX = "idx_addressed_events_actor_unread"
REQUEST_TABLE = "decision_requests"
RETIRED_COLUMN = "blocking"
RETIRED_KIND = "strategy_revision_review"
KIND_CONSTRAINT = "decision_requests_kind_check"
RETIRED_EVENT_NAMES = ("InboxNotificationRead", "ItemBlocked", "ItemUnblocked")

_QUOTED = re.compile(r"'([^']+)'")


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _kind_check_rows(conn: Any) -> list[tuple[str, str]]:
    """Every CHECK on the request table that constrains ``kind``."""
    rows = conn.execute(
        "SELECT con.conname, pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c'",
        (REQUEST_TABLE,),
    ).fetchall()
    return [
        (str(row[0]), str(row[1]))
        for row in rows
        if "kind" in str(row[1]).lower() and _QUOTED.search(str(row[1]))
    ]


def _retired_kind_rows(conn: Any) -> int:
    marker = _marker(conn)
    row = conn.execute(
        f"SELECT COUNT(*) FROM {REQUEST_TABLE} WHERE kind = {marker}",
        (RETIRED_KIND,),
    ).fetchone()
    return int(row[0] or 0)


def apply(conn: Any) -> None:
    """Remove the deliveries, the retired kind's rows, and the blocking flag."""
    marker = _marker(conn)
    if _table_exists(conn, DELIVERY_TABLE):
        if _index_exists(conn, DELIVERY_INDEX, DELIVERY_TABLE):
            conn.execute(f'DROP INDEX IF EXISTS "{DELIVERY_INDEX}"')
        conn.execute(f'DROP TABLE "{DELIVERY_TABLE}"')

    if _table_exists(conn, REQUEST_TABLE):
        # Authority rows cascade from the request row, but the delete is
        # written explicitly so a database whose foreign keys predate the
        # cascade still ends with no orphans.
        for table in (
            "decision_request_role_authorities",
            "decision_request_actor_authorities",
        ):
            if not _table_exists(conn, table):
                continue
            conn.execute(
                f"DELETE FROM {table} WHERE request_id IN "
                f"(SELECT id FROM {REQUEST_TABLE} WHERE kind = {marker})",
                (RETIRED_KIND,),
            )
        conn.execute(
            f"DELETE FROM {REQUEST_TABLE} WHERE kind = {marker}",
            (RETIRED_KIND,),
        )
        if db_backend.connection_is_postgres(conn):
            checks = _kind_check_rows(conn)
            desired = set(DECISION_REQUEST_KINDS)
            if not (
                len(checks) == 1
                and set(_QUOTED.findall(checks[0][1])) == desired
            ):
                for name, _definition in checks:
                    escaped = name.replace('"', '""')
                    conn.execute(
                        f'ALTER TABLE "{REQUEST_TABLE}" DROP CONSTRAINT "{escaped}"'
                    )
                values = ", ".join(f"'{value}'" for value in DECISION_REQUEST_KINDS)
                conn.execute(
                    f"ALTER TABLE {REQUEST_TABLE} ADD CONSTRAINT {KIND_CONSTRAINT} "
                    f"CHECK(kind IN ({values}))"
                )
        if _column_exists(conn, REQUEST_TABLE, RETIRED_COLUMN):
            conn.execute(
                f'ALTER TABLE "{REQUEST_TABLE}" DROP COLUMN "{RETIRED_COLUMN}"'
            )

    if _table_exists(conn, "event_registry"):
        slots = ", ".join(marker for _ in RETIRED_EVENT_NAMES)
        conn.execute(
            f"DELETE FROM event_registry WHERE event_name IN ({slots})",
            RETIRED_EVENT_NAMES,
        )


def invariants(conn: Any) -> None:
    """Prove the substrate, the retired kind, and the flag are all gone."""
    assert not _table_exists(conn, DELIVERY_TABLE), (
        f"{DELIVERY_TABLE} must be absent after convergence"
    )
    if _table_exists(conn, REQUEST_TABLE):
        assert not _column_exists(conn, REQUEST_TABLE, RETIRED_COLUMN), (
            f"{REQUEST_TABLE}.{RETIRED_COLUMN} must be absent after convergence"
        )
        assert _retired_kind_rows(conn) == 0, (
            f"{REQUEST_TABLE} must carry no {RETIRED_KIND} rows after convergence"
        )
        if db_backend.connection_is_postgres(conn):
            for _name, definition in _kind_check_rows(conn):
                assert RETIRED_KIND not in definition, (
                    f"{REQUEST_TABLE}.kind must not admit {RETIRED_KIND}"
                )
    if _table_exists(conn, "event_registry"):
        marker = _marker(conn)
        slots = ", ".join(marker for _ in RETIRED_EVENT_NAMES)
        row = conn.execute(
            f"SELECT COUNT(*) FROM event_registry WHERE event_name IN ({slots})",
            RETIRED_EVENT_NAMES,
        ).fetchone()
        assert int(row[0] or 0) == 0, (
            "event_registry must carry no retired notification event rows"
        )


__all__ = [
    "DELIVERY_INDEX",
    "DELIVERY_TABLE",
    "KIND_CONSTRAINT",
    "MINIMUM_SERVING_VERSION",
    "REQUEST_TABLE",
    "RETIRED_COLUMN",
    "RETIRED_EVENT_NAMES",
    "RETIRED_KIND",
    "apply",
    "invariants",
]
