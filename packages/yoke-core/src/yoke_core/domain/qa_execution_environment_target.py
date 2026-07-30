"""Immutable environment identity and endpoint snapshot for QA execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PLATFORM_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain import db_backend, qa_hosted_runtime_identity as hosted_identity
from yoke_core.domain.qa_case_release_channel import require_case_release_channel


class QaExecutionTargetError(ValueError):
    """A QA plan or case cannot resolve one safe execution target."""


def _mapping_rows(cursor: Any) -> list[dict[str, Any]]:
    """Normalize rows from both Yoke and portable fleet connections."""
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def canonical_target(target: Mapping[str, Any]) -> str:
    return json.dumps(dict(target), sort_keys=True, separators=(",", ":"))


def target_digest(target: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_target(target).encode("utf-8")).hexdigest()


def _decode(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError) as exc:
        raise QaExecutionTargetError(
            "QA execution target environment settings are invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise QaExecutionTargetError(
            "QA execution target environment settings must be an object"
        )
    return value


def _url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise QaExecutionTargetError(f"QA target endpoint is not an HTTP URL: {text!r}")
    return text


def _host_url(value: Any) -> str:
    text = str(value or "").strip()
    return _url(text if "://" in text else f"https://{text}") if text else ""


def runtime_environment_name() -> str:
    """Return the normalized runtime environment selected for QA."""
    return (
        str(
            os.environ.get("YOKE_ENVIRONMENT")
            or os.environ.get("APP_ENV")
            or "development"
        )
        .strip()
        .lower()
    )


def require_runtime_target(target: Mapping[str, Any]) -> None:
    """Refuse cross-environment dispatch in hosted Stage and Production."""
    runtime = runtime_environment_name()
    selected = str(target["environment"]["name"]).strip().lower()
    aliases = {"production": "prod", "staging": "stage"}
    runtime = aliases.get(runtime, runtime)
    selected = aliases.get(selected, selected)
    if runtime in {"prod", "stage"} and selected != runtime:
        raise QaExecutionTargetError(
            f"runtime environment {runtime!r} cannot execute QA target {selected!r}"
        )


def _yoke_endpoints(environment: str, tenant_slug: str) -> dict[str, Any]:
    aliases = {"production": "prod", "staging": "stage"}
    selected = aliases.get(environment.lower(), environment.lower())
    if selected not in {"prod", "stage"}:
        return {}
    app_url = HOSTED_STAGE_PLATFORM_URL if selected == "stage" else HOSTED_PLATFORM_URL
    installer_base = (
        DISTRIBUTION_STAGE_URL if selected == "stage" else DISTRIBUTION_PROD_URL
    )
    release_channel = "latest" if selected == "stage" else "stable"
    return {
        "api_url": f"{app_url}/api/orgs/{tenant_slug}",
        "app_url": app_url,
        "installer_base_url": installer_base,
        "installer_url": f"{installer_base}/install",
        "release_channel": release_channel,
        "capability_endpoints": {
            "browser_authorization": app_url,
            "distribution": installer_base,
        },
    }


def _generic_endpoints(row: Mapping[str, Any], settings: Mapping[str, Any]) -> dict:
    hosts = settings.get("hosts")
    hosts = hosts if isinstance(hosts, Mapping) else {}
    distribution = settings.get("distribution")
    distribution = distribution if isinstance(distribution, Mapping) else {}
    qa = settings.get("qa")
    qa = qa if isinstance(qa, Mapping) else {}
    capabilities = qa.get("capability_endpoints")
    capabilities = capabilities if isinstance(capabilities, Mapping) else {}
    app_url = _url(row.get("url")) or _host_url(hosts.get("app"))
    api_url = _host_url(hosts.get("api")) or app_url
    installer_base = _url(distribution.get("base_url"))
    release_channel = str(distribution.get("channel") or "").strip()
    return {
        "api_url": api_url,
        "app_url": app_url,
        "installer_base_url": installer_base,
        "installer_url": f"{installer_base}/install" if installer_base else "",
        "release_channel": release_channel,
        "capability_endpoints": {
            str(key): _url(value) for key, value in capabilities.items()
        },
    }


def resolve_plan_execution_target(
    conn: Any,
    *,
    plan_id: int,
    require_runtime_match: bool = True,
) -> dict[str, Any]:
    """Resolve the plan's environment binding into one identity snapshot."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cursor = conn.execute(
        "SELECT qp.target_environment_id, p.id AS project_id, "
        "p.slug AS project_slug, p.name AS project_name, "
        "o.id AS tenant_id, o.slug AS tenant_slug, o.name AS tenant_name, "
        "s.id AS site_id, e.id AS environment_id, e.name AS environment_name, "
        "e.url, e.settings "
        "FROM qa_plans qp JOIN projects p ON p.id=qp.project_id "
        "JOIN organizations o ON o.id=p.org_id "
        "LEFT JOIN environments e ON e.id=qp.target_environment_id "
        "LEFT JOIN sites s ON s.id=e.site "
        f"WHERE qp.id={marker}",
        (int(plan_id),),
    )
    rows = _mapping_rows(cursor)
    row = rows[0] if rows else None
    if row is None:
        raise QaExecutionTargetError(f"QA plan {plan_id} not found")
    if not row["target_environment_id"]:
        raise QaExecutionTargetError(
            f"QA plan {plan_id} has no execution environment target"
        )
    if row["environment_id"] is None or row["site_id"] is None:
        raise QaExecutionTargetError("QA plan execution environment is unavailable")
    try:
        hosted_identity.require_plan_environment_access(
            conn,
            plan_project_id=int(row["project_id"]),
            environment_id=str(row["environment_id"]),
        )
    except ValueError as exc:
        raise QaExecutionTargetError(str(exc)) from exc
    settings = _decode(row["settings"])
    environment_name = str(row["environment_name"])
    endpoints = (
        _yoke_endpoints(environment_name, str(row["tenant_slug"]))
        if str(row["project_slug"]) == "yoke"
        else _generic_endpoints(row, settings)
    )
    target = {
        "schema": 1,
        "tenant": {
            "id": int(row["tenant_id"]),
            "slug": str(row["tenant_slug"]),
            "name": str(row["tenant_name"]),
        },
        "project": {
            "id": int(row["project_id"]),
            "slug": str(row["project_slug"]),
            "name": str(row["project_name"]),
        },
        "site": {"id": str(row["site_id"])},
        "environment": {
            "id": str(row["environment_id"]),
            "name": environment_name,
        },
        "endpoints": endpoints,
    }
    if require_runtime_match:
        require_runtime_target(target)
    return target


def select_backfill_environment(conn: Any, *, project_id: int) -> str:
    """Select the current hosted runtime's one project environment."""
    rows = [
        {
            "id": row["environment_id"],
            "name": row["environment_name"],
        }
        for row in hosted_identity.eligible_plan_environment_rows(
            conn,
            plan_project_id=int(project_id),
        )
    ]
    runtime = runtime_environment_name()
    aliases = {"production": "prod", "staging": "stage"}
    runtime = aliases.get(runtime, runtime)
    matches = [
        row
        for row in rows
        if aliases.get(str(row["name"]).lower(), str(row["name"]).lower()) == runtime
    ]
    if len(matches) == 1:
        return str(matches[0]["id"])
    if runtime not in {"prod", "stage"} and len(rows) == 1:
        return str(rows[0]["id"])
    raise QaExecutionTargetError(
        f"project {project_id} cannot resolve one environment for runtime {runtime!r}"
    )


def only_project_environment(conn: Any, *, project_id: int) -> str | None:
    """Return a sole declared project environment for internal compatibility."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "sites") or not _table_exists(conn, "environments"):
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
        f"WHERE s.project_id={marker} ORDER BY e.id",
        (int(project_id),),
    ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    return str(row["id"] if hasattr(row, "keys") else row[0])


def validate_plan_target_environment(
    conn: Any,
    *,
    project_id: int,
    environment_id: str,
) -> None:
    """Require an authorized environment compatible with this runtime."""
    try:
        target = hosted_identity.require_plan_environment_access(
            conn,
            plan_project_id=int(project_id),
            environment_id=str(environment_id),
        )
    except ValueError as exc:
        raise QaExecutionTargetError(str(exc)) from exc
    environment_name = target["environment_name"]
    require_runtime_target({"environment": {"name": environment_name}})


def _known_yoke_hosts() -> set[str]:
    return {
        urlsplit(value).netloc
        for value in (
            DISTRIBUTION_PROD_URL,
            DISTRIBUTION_STAGE_URL,
            HOSTED_PLATFORM_URL,
            HOSTED_STAGE_PLATFORM_URL,
        )
    }


def _walk(value: Any, *, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path=f"{path}[{index}]")
    else:
        yield path, value


_URL_PATTERN = re.compile(r"https?://[^\s'\"()<>\[\],]+")


def require_case_target(
    case: Mapping[str, Any],
    target: Mapping[str, Any],
) -> None:
    """Reject an endpoint or environment belonging to another Yoke target."""
    environment = {"production": "prod", "staging": "stage"}.get(
        str(target["environment"]["name"]).lower(),
        str(target["environment"]["name"]).lower(),
    )
    endpoints = target["endpoints"]
    try:
        require_case_release_channel(
            case,
            expected=str(endpoints.get("release_channel") or "").strip(),
        )
    except ValueError as exc:
        raise QaExecutionTargetError(str(exc)) from exc
    target_hosts = {
        urlsplit(str(value)).netloc
        for key, value in endpoints.items()
        if key.endswith("_url") and value
    }
    known_hosts = _known_yoke_hosts()
    for path, value in _walk(case):
        key = path.rsplit(".", 1)[-1]
        if key in {"active_env", "target_env", "environment"} and isinstance(
            value, str
        ):
            normalized = {"production": "prod", "staging": "stage"}.get(
                value.lower(), value.lower()
            )
            if normalized in {"prod", "stage"} and normalized != environment:
                raise QaExecutionTargetError(
                    f"mixed-environment QA case value at {path}: {value!r}"
                )
        if not isinstance(value, str):
            continue
        for token in _URL_PATTERN.findall(value):
            parsed = urlsplit(token.rstrip(".;:"))
            if parsed.netloc in known_hosts and parsed.netloc not in target_hosts:
                raise QaExecutionTargetError(
                    f"mixed-environment QA endpoint at {path}: {parsed.netloc}"
                )
