"""Admit non-gating operator questions after the serving build converges."""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists

from yoke_core.domain.migration_serving_version import NEXT_RELEASE

MINIMUM_SERVING_VERSION = NEXT_RELEASE

REQUEST_TABLE = "decision_requests"
KIND_CONSTRAINT = "decision_requests_kind_check"

#: The complete kind vocabulary after this entry.
ALL_KINDS = (
    "deployment_stage_approval",
    "qa_needs_review",
    "lifecycle_transition_approval",
    "machine_approval",
    "merge_candidate_review",
    "operator_question",
)

_QUOTED = re.compile(r"'([^']+)'")


def _kind_checks(conn: Any) -> list[tuple[str, str]]:
    """Every CHECK on the request table that constrains ``kind``.

    Discovered rather than assumed: a database whose table was created
    outside this history may carry the constraint under an auto-generated
    name, and dropping only the expected name would leave the narrow check
    in place beside the widened one -- a refusal nothing explains.
    """
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


def apply(conn: Any) -> None:
    if not _table_exists(conn, REQUEST_TABLE):
        return
    if not db_backend.connection_is_postgres(conn):
        # A non-Postgres database created its table fresh from the current
        # schema module, so it never carried a narrower constraint to widen.
        return
    checks = _kind_checks(conn)
    desired = set(ALL_KINDS)
    if len(checks) == 1 and set(_QUOTED.findall(checks[0][1])) == desired:
        return
    for name, _definition in checks:
        escaped = name.replace('"', '""')
        conn.execute(
            f'ALTER TABLE "{REQUEST_TABLE}" DROP CONSTRAINT IF EXISTS "{escaped}"'
        )
    values = ", ".join(f"'{value}'" for value in ALL_KINDS)
    conn.execute(
        f'ALTER TABLE "{REQUEST_TABLE}" ADD CONSTRAINT "{KIND_CONSTRAINT}" '
        f"CHECK(kind IN ({values}))"
    )


def invariants(conn: Any) -> None:
    """No CHECK on the table may reject a kind this entry admits."""
    if not _table_exists(conn, REQUEST_TABLE) or not db_backend.connection_is_postgres(
        conn
    ):
        return
    checks = _kind_checks(conn)
    assert checks, f"{REQUEST_TABLE}.kind carries no CHECK after apply"
    for name, definition in checks:
        for kind in ALL_KINDS:
            assert f"'{kind}'" in definition, (
                f"{name} does not admit {kind!r}: {definition}"
            )


__all__ = [
    "ALL_KINDS",
    "KIND_CONSTRAINT",
    "REQUEST_TABLE",
    "apply",
    "invariants",
]
