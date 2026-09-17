"""Bind one QA case to a project's declared environment as its target.

A plan reaches this through its own ``target_environment_id``; a case that
belongs to no plan reaches it by naming the environment on the requirement.
Both land on the same snapshot shape, the same authorization read, and the
same runtime guard, so a case outside a plan is bound to a real reviewed
endpoint rather than dispatched at nothing.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from yoke_core.domain import db_backend, qa_hosted_runtime_identity as hosted_identity
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    _decode,
    _generic_endpoints,
    _mapping_rows,
    _yoke_endpoints,
    require_runtime_target,
)


_IDENTITY_SQL = (
    "SELECT p.id AS project_id, p.slug AS project_slug, p.name AS project_name, "
    "o.id AS tenant_id, o.slug AS tenant_slug, o.name AS tenant_name, "
    "s.name AS site_name, e.id AS environment_id, e.name AS environment_name, "
    "e.url, e.settings "
    "FROM environments e JOIN sites s ON s.id=e.site "
    "JOIN projects p ON p.id=s.project_id "
    "JOIN organizations o ON o.id=p.org_id "
    "WHERE s.project_id={p} AND e.name={p}"
)


def environment_execution_target(
    conn: Any,
    identity: Mapping[str, Any],
    *,
    require_runtime_match: bool = True,
) -> dict[str, Any]:
    """Assemble the immutable snapshot for one resolved environment row.

    *identity* carries the tenant, project, site, and environment columns
    already read by the caller, so a plan and a plan-less case share one
    assembly instead of each describing the same environment its own way.
    """
    if identity["environment_id"] is None or identity["site_name"] is None:
        raise QaExecutionTargetError("QA plan execution environment is unavailable")
    try:
        hosted_identity.require_plan_environment_access(
            conn,
            plan_project_id=int(identity["project_id"]),
            environment_id=int(identity["environment_id"]),
        )
    except ValueError as exc:
        raise QaExecutionTargetError(str(exc)) from exc
    settings = _decode(identity["settings"])
    environment_name = str(identity["environment_name"])
    # Yoke's own hosted tiers are addressed by the release constants. Every
    # other environment of that project -- a workstation's own view of its
    # universe -- is described by its row alone, which is the only place its
    # address can come from.
    endpoints = (
        _yoke_endpoints(environment_name, str(identity["tenant_slug"]))
        if str(identity["project_slug"]) == "yoke"
        else {}
    ) or _generic_endpoints(identity, settings)
    target = {
        "schema": 2,
        "tenant": {
            "id": int(identity["tenant_id"]),
            "slug": str(identity["tenant_slug"]),
            "name": str(identity["tenant_name"]),
        },
        "project": {
            "id": int(identity["project_id"]),
            "slug": str(identity["project_slug"]),
            "name": str(identity["project_name"]),
        },
        "site": {"name": str(identity["site_name"])},
        "environment": {"name": environment_name},
        "endpoints": endpoints,
    }
    if require_runtime_match:
        require_runtime_target(target)
    return target


def bind_item_named_target(
    conn: Any,
    *,
    item_id: int,
    row: dict[str, Any],
) -> str:
    """Fill named-target snapshot columns; return a refusal message or ''."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    found = conn.execute(
        f"SELECT project_id FROM items WHERE id={marker}",
        (int(item_id),),
    ).fetchone()
    if found is None or found[0] is None:
        return "requirement has no project to resolve an execution target against"
    project_id = int(found[0])
    try:
        apply_named_target_to_requirement_row(
            conn, project_id=int(project_id), row=row
        )
    except QaExecutionTargetError as exc:
        return str(exc)
    return ""


def persistable_named_environment_target(
    conn: Any,
    *,
    project_id: int,
    environment_name: str,
) -> dict[str, Any] | None:
    """Return the snapshot when *environment_name* is this project's to bind.

    An unregistered name stays unbound so authoring can defer the target. A
    name registered only on another project is refused rather than stored as
    a draft label that would later execute against the wrong universe.
    """
    name = str(environment_name or "").strip()
    if not name:
        return None
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "environments"):
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    owners = [
        int(row["project_id"])
        for row in _mapping_rows(
            conn.execute(
                "SELECT p.id AS project_id FROM environments e "
                "JOIN sites s ON s.id=e.site "
                "JOIN projects p ON p.id=s.project_id WHERE e.name=" + marker,
                (name,),
            )
        )
    ]
    if not owners:
        return None
    if int(project_id) not in owners:
        others = ", ".join(str(pid) for pid in sorted(set(owners)))
        raise QaExecutionTargetError(
            f"QA case names environment {name!r}, which belongs to project "
            f"{others}, not project {project_id}. Name an environment "
            "registered to this project, or omit --target-env until that "
            "binding exists."
        )
    return resolve_named_environment_execution_target(
        conn,
        project_id=int(project_id),
        environment_name=name,
    )


def apply_named_target_to_requirement_row(
    conn: Any,
    *,
    project_id: int,
    row: dict[str, Any],
) -> None:
    """Fill execution-target columns from a named authorized environment."""
    from yoke_core.domain.qa_execution_environment_target import (
        canonical_target,
        target_digest,
    )

    target = persistable_named_environment_target(
        conn,
        project_id=int(project_id),
        environment_name=str(row.get("target_env") or ""),
    )
    if target is None:
        row["execution_target_json"] = None
        row["execution_target_digest"] = None
        return
    row["execution_target_json"] = canonical_target(target)
    row["execution_target_digest"] = target_digest(target)


def persist_requirement_target_snapshot(
    conn: Any,
    requirement_id: int,
    row: dict[str, Any],
) -> None:
    """Write snapshot columns when this database actually has them."""
    from yoke_core.domain.schema_common import _column_exists

    if not _column_exists(conn, "qa_requirements", "execution_target_json"):
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE qa_requirements SET execution_target_json={marker}, "
        f"execution_target_digest={marker} WHERE id={marker}",
        (
            row["execution_target_json"],
            row["execution_target_digest"],
            int(requirement_id),
        ),
    )


def resolve_named_environment_execution_target(
    conn: Any,
    *,
    project_id: int,
    environment_name: str,
) -> dict[str, Any]:
    """Resolve the environment a case names into its execution target.

    Unlike a plan target this one refuses an environment with no reviewable
    address. A case exists to observe something, so a snapshot carrying
    identity and no endpoint would prove only that the environment is
    registered -- never that the evidence came from it.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = _mapping_rows(
        conn.execute(
            _IDENTITY_SQL.replace("{p}", marker),
            (int(project_id), str(environment_name)),
        )
    )
    if not rows:
        raise QaExecutionTargetError(
            f"QA case names environment {environment_name!r}, which project "
            f"{project_id} has not registered"
        )
    target = environment_execution_target(conn, rows[0])
    if not str(target["endpoints"].get("app_url") or "").strip():
        raise QaExecutionTargetError(
            f"environment {environment_name!r} declares no reviewable URL, so a "
            "QA case bound to it could not be observed there. Record the "
            "address in that environment's settings under hosts.app first"
        )
    return target


def _origin(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""


def require_case_endpoint(
    case: Mapping[str, Any],
    target: Mapping[str, Any],
) -> None:
    """Require the address a case browses to be the one its target declares.

    Identity and authorization say the environment is real and reachable by
    this actor; only this says the screenshots came from it.
    """
    config = case.get("method_config")
    declared = _origin(
        str((config if isinstance(config, Mapping) else {}).get("base_url") or "")
    )
    if not declared:
        return
    expected = _origin(str(target["endpoints"].get("app_url") or ""))
    if declared != expected:
        raise QaExecutionTargetError(
            f"QA case browses {declared}, which is not the "
            f"{str(target['environment']['name'])!r} target endpoint "
            f"{expected or 'missing'}"
        )


__all__ = [
    "apply_named_target_to_requirement_row",
    "bind_item_named_target",
    "environment_execution_target",
    "persist_requirement_target_snapshot",
    "persistable_named_environment_target",
    "require_case_endpoint",
    "resolve_named_environment_execution_target",
]
