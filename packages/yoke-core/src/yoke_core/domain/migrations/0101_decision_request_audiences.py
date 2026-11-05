"""Move decision targeting to audiences and retire the old authority tables."""

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.audience_schema import create_audience_tables
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _add_column_if_not_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

ROLE_TABLE = "decision_request_role_authorities"
ACTOR_TABLE = "decision_request_actor_authorities"


def apply(conn: Any) -> None:
    if not _table_exists(conn, "decision_requests"):
        return
    create_audience_tables(conn, commit=False)
    _add_column_if_not_exists(
        conn, "decision_requests", "audience_id", "INTEGER REFERENCES audiences(id)"
    )
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    roles_exist = _table_exists(conn, ROLE_TABLE)
    actors_exist = _table_exists(conn, ACTOR_TABLE)
    for request in conn.execute(
        "SELECT id, project_id, org_id, audience_id FROM decision_requests ORDER BY id"
    ).fetchall():
        request_id, project_id, org_id, audience_id = request
        if audience_id is not None:
            continue
        rules = []
        if roles_exist:
            rules.extend(
                tuple(row)
                for row in conn.execute(
                    f"SELECT scope_kind, scope_id, role_name FROM {ROLE_TABLE} WHERE request_id = {p} ORDER BY role_name, scope_id",
                    (request_id,),
                ).fetchall()
            )
        if actors_exist:
            rules.extend(
                ("actor", int(row[0]), None)
                for row in conn.execute(
                    f"SELECT actor_id FROM {ACTOR_TABLE} WHERE request_id = {p} ORDER BY actor_id",
                    (request_id,),
                ).fetchall()
            )
        # History may include retired actors or empty old authority sets. Preserve
        # those rules exactly; current human membership is resolved at read time.
        audience_id = conn.execute(
            f"INSERT INTO audiences(project_id, org_id) VALUES ({p}, {p}) RETURNING id",
            (project_id, org_id),
        ).fetchone()[0]
        for position, rule in enumerate(dict.fromkeys(rules)):
            conn.execute(
                "INSERT INTO audience_rules(audience_id, position, scope_kind, scope_id, role_name) "
                f"VALUES ({p}, {p}, {p}, {p}, {p})",
                (audience_id, position, *rule),
            )
        conn.execute(
            f"UPDATE decision_requests SET audience_id = {p} WHERE id = {p}",
            (audience_id, request_id),
        )
    invariants(conn, require_dropped=False)
    conn.execute(f"DROP TABLE IF EXISTS {ROLE_TABLE}")
    conn.execute(f"DROP TABLE IF EXISTS {ACTOR_TABLE}")


def invariants(conn: Any, *, require_dropped: bool = True) -> None:
    if not _table_exists(conn, "decision_requests"):
        return
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM decision_requests r LEFT JOIN audiences a ON a.id = r.audience_id WHERE a.id IS NULL"
        ).fetchone()[0]
        == 0
    )
    if require_dropped:
        assert not _table_exists(conn, ROLE_TABLE)
        assert not _table_exists(conn, ACTOR_TABLE)
