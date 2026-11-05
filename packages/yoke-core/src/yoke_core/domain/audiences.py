"""Create audiences and resolve current human membership in either direction."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_backend
from yoke_core.domain.actor_state import actor_active_sql
from yoke_core.domain.db_savepoint import savepoint


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _refuse(reason: str, detail: str, recovery: str) -> None:
    raise ValueError(compose_refusal(f"{reason}: {detail}", recovery=recovery))


def validate_rules(conn: Any, rules: Iterable[Mapping[str, Any]]) -> list[dict]:
    normalized = []
    p = _p(conn)
    for raw in rules:
        if not isinstance(raw, Mapping):
            _refuse(
                "invalid_audience_rule",
                "Every rule must be an object",
                "Supply scope_kind, scope_id and an optional role_name",
            )
        kind = str(raw.get("scope_kind", ""))
        scope_id = raw.get("scope_id")
        role = raw.get("role_name") or None
        if kind not in ("actor", "org", "project") or (
            not isinstance(scope_id, int) or isinstance(scope_id, bool)
        ):
            _refuse(
                "invalid_audience_rule",
                "A rule needs a scope and integer scope_id",
                "Choose an actor, organization or project",
            )
        table = {"actor": "actors", "org": "organizations", "project": "projects"}[kind]
        exists = conn.execute(
            f"SELECT * FROM {table} WHERE id = {p}", (scope_id,)
        ).fetchone()
        if exists is None or (kind == "actor" and (role or exists["kind"] != "human")):
            _refuse(
                "invalid_audience_rule",
                "The addressed scope is missing or is not a person",
                "Select an existing person, organization or project",
            )
        if (
            role
            and conn.execute(
                f"SELECT 1 FROM roles WHERE name = {p}", (role,)
            ).fetchone()
            is None
        ):
            _refuse(
                "invalid_audience_rule",
                f"Unknown role {role}",
                "Select an existing role",
            )
        rule = {"scope_kind": kind, "scope_id": scope_id, "role_name": role}
        if rule not in normalized:
            normalized.append(rule)
    if not normalized:
        _refuse(
            "empty_audience",
            "An audience needs at least one rule",
            "Add an audience rule",
        )
    return normalized


def create_audience(
    conn: Any,
    *,
    rules: Iterable[Mapping[str, Any]],
    project_id: int | None = None,
    org_id: int | None = None,
    name: str | None = None,
    commit: bool = True,
) -> int:
    if (project_id is None) == (org_id is None):
        _refuse(
            "audience_scope_mismatch",
            "Choose exactly one owning scope",
            "Supply one project or organization",
        )
    p = _p(conn)
    owner = conn.execute(
        f"SELECT * FROM {'projects' if project_id is not None else 'organizations'} WHERE id = {p}",
        (project_id if project_id is not None else org_id,),
    ).fetchone()
    if owner is None:
        _refuse(
            "audience_scope_mismatch",
            "The owner does not exist",
            "Select an existing owner",
        )
    rules = validate_rules(conn, rules)
    owner_org = owner["org_id"] if project_id is not None else org_id
    for rule in rules:
        if rule["scope_kind"] == "org" and rule["scope_id"] != owner_org:
            _refuse(
                "audience_scope_mismatch",
                "The rule names a different organization",
                "Use the owner's organization",
            )
        if rule["scope_kind"] == "project":
            addressed = conn.execute(
                f"SELECT org_id FROM projects WHERE id = {p}", (rule["scope_id"],)
            ).fetchone()
            if (project_id is not None and rule["scope_id"] != project_id) or addressed[
                0
            ] != owner_org:
                _refuse(
                    "audience_scope_mismatch",
                    "The rule names a different project scope",
                    "Use the owning project or a project in the owning organization",
                )
    if name is not None and not name.strip():
        _refuse(
            "invalid_audience_name",
            "The audience name is empty",
            "Choose a nonempty name or omit it for an inline audience",
        )
    name = name.strip() if name else None
    begin_write(conn)
    with savepoint(conn, "audience_create", owns=commit):
        row = conn.execute(
            "INSERT INTO audiences(project_id, org_id, name) "
            f"VALUES ({p}, {p}, {p}) ON CONFLICT DO NOTHING RETURNING id",
            (project_id, org_id, name),
        ).fetchone()
        if row is None:
            _refuse(
                "audience_name_exists",
                "This audience name is already used",
                "Choose a different name or select the existing audience",
            )
        audience_id = int(row[0])
        for position, rule in enumerate(rules):
            conn.execute(
                "INSERT INTO audience_rules(audience_id, position, scope_kind, scope_id, role_name) "
                f"VALUES ({p}, {p}, {p}, {p}, {p})",
                (
                    audience_id,
                    position,
                    rule["scope_kind"],
                    rule["scope_id"],
                    rule["role_name"],
                ),
            )
    if commit:
        conn.commit()
    return audience_id


def audience(conn: Any, audience_id: int) -> dict:
    row = conn.execute(
        f"SELECT * FROM audiences WHERE id = {_p(conn)}", (audience_id,)
    ).fetchone()
    if row is None:
        _refuse(
            "unknown_audience",
            "The audience does not exist",
            "List audiences and select an existing one",
        )
    return dict(row)


def rules_for_audiences(
    conn: Any, audience_ids: Iterable[int]
) -> dict[int, list[dict]]:
    ids = tuple(dict.fromkeys(audience_ids))
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT * FROM audience_rules WHERE audience_id IN ({','.join(_p(conn) for _ in ids)}) "
        "ORDER BY audience_id, position",
        ids,
    ).fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(int(row["audience_id"]), []).append(dict(row))
    return result


def _matches(conn: Any) -> str:
    """One live membership predicate, shared by every audience consumer."""
    return f"""a.kind = 'human' AND {actor_active_sql(conn, "a")} AND (
        (r.scope_kind = 'actor' AND r.scope_id = a.id)
        OR (r.scope_kind = 'org' AND EXISTS (
            SELECT 1 FROM actor_org_roles ar JOIN roles ro ON ro.id = ar.role_id
            WHERE ar.actor_id = a.id AND ar.org_id = r.scope_id
                AND (r.role_name IS NULL OR ro.name = r.role_name)))
        OR (r.scope_kind = 'project' AND EXISTS (
            SELECT 1 FROM actor_project_roles ar JOIN roles ro ON ro.id = ar.role_id
            WHERE ar.actor_id = a.id AND ar.project_id = r.scope_id
                AND (r.role_name IS NULL OR ro.name = r.role_name))))"""


def member_matches(
    conn: Any, audience_id: int, actor_id: int | None = None
) -> list[dict]:
    p = _p(conn)
    actor_filter = f" AND a.id = {p}" if actor_id is not None else ""
    params = (audience_id, actor_id) if actor_id is not None else (audience_id,)
    return [
        dict(row)
        for row in conn.execute(
            "SELECT a.id AS actor_id, r.position, r.scope_kind, r.scope_id, r.role_name "
            "FROM audience_rules r CROSS JOIN actors a "
            f"WHERE r.audience_id = {p}{actor_filter} AND {_matches(conn)} "
            "ORDER BY CASE WHEN r.scope_kind = 'actor' THEN 0 ELSE 1 END, r.position, a.id",
            params,
        ).fetchall()
    ]


def includes_actor(conn: Any, audience_id: int, actor_id: int) -> bool:
    return bool(member_matches(conn, audience_id, actor_id))


def audiences_for_actor(conn: Any, actor_id: int) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT DISTINCT r.audience_id FROM audience_rules r CROSS JOIN actors a "
        f"WHERE a.id = {_p(conn)} AND {_matches(conn)} ORDER BY r.audience_id",
        (actor_id,),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def named_audiences(
    conn: Any, *, project_id: int | None = None, org_id: int | None = None
) -> list[dict]:
    column = "project_id" if project_id is not None else "org_id"
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM audiences WHERE {column} = {_p(conn)} AND name IS NOT NULL ORDER BY name, id",
            (project_id if project_id is not None else org_id,),
        ).fetchall()
    ]


def rule_actor_ids(conn: Any, rule: Mapping[str, Any]) -> tuple[int, ...]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT a.id FROM actors a CROSS JOIN "
        f"(SELECT {p} AS scope_kind, {p} AS scope_id, {p} AS role_name) r "
        f"WHERE {_matches(conn)} ORDER BY a.id",
        (rule["scope_kind"], rule["scope_id"], rule.get("role_name")),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def begin_write(conn: Any) -> None:
    """Keep nested savepoints inside a real caller transaction on SQLite."""
    if not db_backend.connection_is_postgres(conn) and not conn.in_transaction:
        conn.execute("BEGIN")


def member_matches_for_audiences(
    conn: Any, audience_ids: Iterable[int]
) -> dict[int, list[dict]]:
    ids = tuple(dict.fromkeys(audience_ids))
    if not ids:
        return {}
    p = _p(conn)
    rows = conn.execute(
        "SELECT r.audience_id, a.id AS actor_id, r.position, r.scope_kind, r.scope_id, r.role_name "
        "FROM audience_rules r CROSS JOIN actors a "
        f"WHERE r.audience_id IN ({','.join(p for _ in ids)}) AND {_matches(conn)} "
        "ORDER BY CASE WHEN r.scope_kind = 'actor' THEN 0 ELSE 1 END, r.position, a.id",
        ids,
    ).fetchall()
    result = {}
    for row in rows:
        result.setdefault(int(row["audience_id"]), []).append(dict(row))
    return result
