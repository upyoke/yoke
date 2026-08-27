"""Project-scoped execution targets for environmentless command QA plans."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlsplit

from yoke_core.domain import db_backend


PROJECT_TARGET_SCHEMA = 3
PROJECT_TARGET_KIND = "project"
ENVIRONMENT_TARGET_MODE = "environment"
RUNTIME_BASE_URL_TARGET_MODE = "runtime-base-url"
LOCAL_COMMAND_METHOD_ID = "command"
CI_COMMAND_METHOD_ID = "command-ci"
PROJECT_TARGET_METHODS = frozenset({LOCAL_COMMAND_METHOD_ID, CI_COMMAND_METHOD_ID})
PROJECT_COMMAND_SCOPES = frozenset({"quick", "full"})
DEPLOYED_COMMAND_SCOPES = frozenset({"e2e", "smoke"})


def is_project_execution_target(target: Mapping[str, Any]) -> bool:
    """Return whether *target* is the immutable project-target variant."""
    return (
        target.get("schema") == PROJECT_TARGET_SCHEMA
        and target.get("target_kind") == PROJECT_TARGET_KIND
    )


def registered_command_target_mode(
    *,
    scope: str,
    ci_workflow: str,
    target_environment: str | None,
    requires_base_url: bool | None,
) -> str:
    """Validate registration inputs and return the selected target mode."""
    environment = str(target_environment or "").strip()
    if scope in PROJECT_COMMAND_SCOPES:
        if environment or requires_base_url is not None:
            raise ValueError(
                f"registered {scope} commands are project-targeted; omit "
                "--environment and --requires-base-url"
            )
        return PROJECT_TARGET_KIND
    if scope not in DEPLOYED_COMMAND_SCOPES:
        raise ValueError(f"unsupported registered command scope {scope!r}")
    local_base_url = requires_base_url is True
    if ci_workflow:
        if local_base_url:
            raise ValueError(
                f"CI-routed {scope} commands cannot use --requires-base-url; "
                "bind --environment SITE/NAME|ENV_ID"
            )
        if not environment:
            raise ValueError(
                f"CI-routed {scope} commands require --environment "
                "SITE/NAME|ENV_ID"
            )
        return ENVIRONMENT_TARGET_MODE
    if bool(environment) == local_base_url:
        raise ValueError(
            f"local {scope} commands require exactly one target: "
            "--environment SITE/NAME|ENV_ID or --requires-base-url"
        )
    return (
        ENVIRONMENT_TARGET_MODE if environment else RUNTIME_BASE_URL_TARGET_MODE
    )


def _decode_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError) as exc:
        raise ValueError("command case method_config is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("command case method_config must be an object")
    return value


def _case_rows(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cursor = conn.execute(
        "SELECT method_id, method_config FROM qa_plan_cases "
        f"WHERE plan_id={marker} ORDER BY position",
        (int(plan_id),),
    )
    columns = [
        str(getattr(column, "name", None) or column[0])
        for column in cursor.description
    ]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row, strict=True))
        for row in cursor.fetchall()
    ]


def _project_target_allowed(cases: list[Mapping[str, Any]]) -> bool:
    return bool(cases) and all(
        str(case.get("method_id") or "") in PROJECT_TARGET_METHODS for case in cases
    )


def _require_local_base_url_contract(
    method_id: str,
    config: Mapping[str, Any],
) -> None:
    if method_id == CI_COMMAND_METHOD_ID and config.get("requires_base_url"):
        raise ValueError(
            "CI command cases cannot use the local requires_base_url contract; "
            "bind a deployment environment"
        )


def resolve_project_execution_target(
    conn: Any,
    *,
    plan_id: int,
    identity: Mapping[str, Any],
    allow_unbound: bool,
) -> dict[str, Any] | None:
    """Build a project target when every plan case can run without an environment."""
    cases = _case_rows(conn, plan_id)
    if not _project_target_allowed(cases):
        if allow_unbound:
            return None
        raise ValueError(
            f"QA plan {plan_id} has no deployment environment target; only "
            "command and command-ci cases may use a project target"
        )
    for case in cases:
        method_id = str(case["method_id"])
        _require_local_base_url_contract(
            method_id,
            _decode_config(case["method_config"]),
        )
    return {
        "schema": PROJECT_TARGET_SCHEMA,
        "target_kind": PROJECT_TARGET_KIND,
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
        "endpoints": {},
    }


def require_project_target_case(
    case: Mapping[str, Any],
    target: Mapping[str, Any],
) -> None:
    """Refuse a materialized case that cannot use a project target."""
    method_id = str(case.get("method_id") or "")
    if method_id not in PROJECT_TARGET_METHODS:
        raise ValueError(
            f"QA method {method_id or 'missing'!r} requires a deployment "
            "environment target"
        )
    config = _decode_config(case.get("method_config"))
    _require_local_base_url_contract(method_id, config)
    project_id = case.get("project_id")
    if project_id is not None and int(project_id) != int(target["project"]["id"]):
        raise ValueError("QA case project does not match its execution target")


def _http_url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"base_url must be an HTTP(S) URL, got {text!r}")
    return text


def resolve_execution_base_url(
    target: Mapping[str, Any],
    requirements: list[Mapping[str, Any]],
    explicit_base_url: str,
) -> str:
    """Select the base URL allowed by an immutable execution target."""
    supplied = _http_url(explicit_base_url) if str(explicit_base_url).strip() else ""
    if is_project_execution_target(target):
        for requirement in requirements:
            require_project_target_case(requirement, target)
        requires_base_url = any(
            bool(_decode_config(row.get("method_config")).get("requires_base_url"))
            for row in requirements
        )
        if requires_base_url and not supplied:
            raise ValueError(
                "this project-targeted Command plan requires --base-url with "
                "an HTTP(S) URL"
            )
        return supplied

    endpoints = target.get("endpoints")
    if not isinstance(endpoints, Mapping):
        raise ValueError("QA execution target has invalid endpoints")
    allowed = {
        str(value).rstrip("/")
        for key, value in endpoints.items()
        if str(key).endswith("_url") and isinstance(value, str) and value
    }
    if supplied and supplied not in allowed:
        raise ValueError("explicit base_url does not belong to the execution target")
    return supplied or str(endpoints.get("app_url") or endpoints.get("api_url") or "")


__all__ = [
    "DEPLOYED_COMMAND_SCOPES",
    "ENVIRONMENT_TARGET_MODE",
    "CI_COMMAND_METHOD_ID",
    "LOCAL_COMMAND_METHOD_ID",
    "PROJECT_COMMAND_SCOPES",
    "PROJECT_TARGET_KIND",
    "PROJECT_TARGET_METHODS",
    "PROJECT_TARGET_SCHEMA",
    "RUNTIME_BASE_URL_TARGET_MODE",
    "is_project_execution_target",
    "registered_command_target_mode",
    "require_project_target_case",
    "resolve_execution_base_url",
    "resolve_project_execution_target",
]
