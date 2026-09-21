"""Environment behavior is declared on the environment, never inferred from its name.

An environment's name is an arbitrary identifier. Hosted endpoints, QA
execution gating, release membership, the paired admin connection, the
serving connection a warm-up calls, observability, and the production
role are facts on that environment's settings document. A missing
declaration is a named refusal, not an empty mapping and not production
behavior borrowed from a conventional name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.refusal_recovery import compose_refusal
from yoke_core.domain.settings_cas import apply_key_path_assignments, read_key_path

HOSTS_APP_PATH = "hosts.app"
HOSTS_API_PATH = "hosts.api"
DISTRIBUTION_BASE_URL_PATH = "distribution.base_url"
DISTRIBUTION_CHANNEL_PATH = "distribution.channel"
QA_RESTRICT_EXECUTION_PATH = "qa.restrict_execution_to_self"
QA_HOSTED_RUNTIME_PATH = "qa.hosted_runtime"
RELEASE_ENVIRONMENT_PATH = "release.environment"
ADMIN_CONNECTION_PATH = "release.admin_connection"
SERVING_CONNECTION_PATH = "deploy.serving_connection"
EMIT_LOG_METRICS_PATH = "observability.emit_log_metrics"
PRODUCTION_ROLE_PATH = "role.production"

ENDPOINT_PATHS = (
    HOSTS_APP_PATH,
    HOSTS_API_PATH,
    DISTRIBUTION_BASE_URL_PATH,
    DISTRIBUTION_CHANNEL_PATH,
)
URL_ENDPOINT_PATHS = frozenset(
    {HOSTS_APP_PATH, HOSTS_API_PATH, DISTRIBUTION_BASE_URL_PATH}
)


def endpoint_fact_report(settings: Mapping[str, Any] | None) -> str:
    """Every endpoint fact this refusal evaluated, including declared ones."""
    parts: list[str] = []
    for path in ENDPOINT_PATHS:
        text = declared_text(settings, path)
        if not text:
            parts.append(f"{path}=absent")
            continue
        if path in URL_ENDPOINT_PATHS and "://" not in text:
            parts.append(f"{path}={text!r} (declared, not a URL: no scheme)")
        else:
            parts.append(f"{path}={text!r}")
    return "; ".join(parts)


class MissingEnvironmentFact(ValueError):
    """One or more required environment settings are absent."""

    def __init__(
        self,
        environment: str,
        paths: str | Sequence[str],
        settings: Mapping[str, Any] | None = None,
    ) -> None:
        self.environment = environment
        self.paths = (paths,) if isinstance(paths, str) else tuple(paths)
        named = ", ".join(self.paths)
        if settings is not None and all(path in ENDPOINT_PATHS for path in self.paths):
            malformed = [
                path
                for path in ENDPOINT_PATHS
                if path in URL_ENDPOINT_PATHS
                and declared_text(settings, path)
                and "://" not in declared_text(settings, path)
            ]
            recovery = (
                "set the absent facts with yoke projects environment-settings "
                f"merge --project <project> --environment {environment} "
                + " ".join(f"--set {path}=<value>" for path in self.paths)
            )
            if malformed:
                recovery += (
                    "; replace declared-but-not-a-URL values before retrying "
                    f"({', '.join(malformed)}) so completing the absent set "
                    "does not promote a scheme-less host to a consumed URL"
                )
            message = compose_refusal(
                f"environment {environment!r} does not declare {named}",
                evaluated=endpoint_fact_report(settings),
                recovery=recovery,
            )
        else:
            message = compose_refusal(
                f"environment {environment!r} does not declare {named}",
                recovery=(
                    "set it via: yoke projects environment-settings merge "
                    "--project <project> --environment "
                    f"{environment} --set {self.paths[0]}=<value>"
                ),
            )
        super().__init__(message)


def _document(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(settings) if isinstance(settings, Mapping) else {}


def declared_text(settings: Mapping[str, Any] | None, path: str) -> str:
    value = read_key_path(_document(settings), path)
    if isinstance(value, str):
        return value.strip()
    return ""


def declared_bool(settings: Mapping[str, Any] | None, path: str) -> bool | None:
    value = read_key_path(_document(settings), path)
    if isinstance(value, bool):
        return value
    return None


def require_declared_text(
    environment: str, settings: Mapping[str, Any] | None, path: str
) -> str:
    text = declared_text(settings, path)
    if not text:
        raise MissingEnvironmentFact(environment, path)
    return text


def settings_from_projection(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Rebuild a settings document from a flat environment-settings projection."""
    return apply_key_path_assignments({}, dict(values or {}))


def decode_settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not str(raw or "").strip():
        return {}
    try:
        document = json_helper.loads_text(str(raw))
    except ValueError:
        return {}
    return dict(document) if isinstance(document, Mapping) else {}


def load_environment_settings(
    conn: Any, project_id: int, environment: str
) -> dict[str, Any]:
    """The named environment's settings on *project_id*, or empty if absent."""
    name = str(environment or "").strip()
    if not name:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT settings FROM environments "
        f"WHERE project_id={marker} AND name={marker}",
        (int(project_id), name),
    ).fetchone()
    if row is None:
        return {}
    return decode_settings(row[0] if not hasattr(row, "keys") else row["settings"])


def endpoint_declaration_state(settings: Mapping[str, Any] | None) -> str:
    present = [path for path in ENDPOINT_PATHS if declared_text(settings, path)]
    if not present:
        return "unstated"
    if len(present) == len(ENDPOINT_PATHS):
        return "complete"
    return "incomplete"


def hosted_endpoints(
    environment: str, settings: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Require the four endpoint facts and assemble the QA snapshot endpoints."""
    missing = [path for path in ENDPOINT_PATHS if not declared_text(settings, path)]
    if missing:
        raise MissingEnvironmentFact(environment, missing, settings=settings)
    app_url = declared_text(settings, HOSTS_APP_PATH).rstrip("/")
    api_url = declared_text(settings, HOSTS_API_PATH).rstrip("/")
    installer_base = declared_text(settings, DISTRIBUTION_BASE_URL_PATH).rstrip("/")
    channel = declared_text(settings, DISTRIBUTION_CHANNEL_PATH)
    return {
        "api_url": api_url,
        "app_url": app_url,
        "installer_base_url": installer_base,
        "installer_url": f"{installer_base}/install" if installer_base else "",
        "release_channel": channel,
        "capability_endpoints": {
            "browser_authorization": app_url,
            "distribution": installer_base,
        },
    }


def restricts_qa_to_self(settings: Mapping[str, Any] | None) -> bool:
    return declared_bool(settings, QA_RESTRICT_EXECUTION_PATH) is True


def is_hosted_runtime(settings: Mapping[str, Any] | None) -> bool:
    return declared_bool(settings, QA_HOSTED_RUNTIME_PATH) is True


def is_release_environment(settings: Mapping[str, Any] | None) -> bool:
    return declared_bool(settings, RELEASE_ENVIRONMENT_PATH) is True


def is_production(settings: Mapping[str, Any] | None) -> bool:
    return declared_bool(settings, PRODUCTION_ROLE_PATH) is True


def emits_log_metrics(settings: Mapping[str, Any] | None) -> bool:
    return declared_bool(settings, EMIT_LOG_METRICS_PATH) is True


def admin_connection_for_environment(
    environment: str, settings: Mapping[str, Any] | None
) -> str:
    return require_declared_text(environment, settings, ADMIN_CONNECTION_PATH)


def serving_connection_for_environment(
    environment: str, settings: Mapping[str, Any] | None
) -> str:
    return require_declared_text(environment, settings, SERVING_CONNECTION_PATH)


def target_is_production(target: Mapping[str, Any]) -> bool:
    role = target.get("role")
    if isinstance(role, Mapping) and "production" in role:
        return bool(role["production"])
    return False


def production_declared_facts(
    *,
    app_url: str,
    api_url: str,
    installer_base_url: str,
    release_channel: str,
    admin_connection: str,
    serving_connection: str,
    production: bool,
) -> dict[str, Any]:
    """The settings document that makes an arbitrary name behave as hosted."""
    return settings_from_projection(
        {
            HOSTS_APP_PATH: app_url,
            HOSTS_API_PATH: api_url,
            DISTRIBUTION_BASE_URL_PATH: installer_base_url,
            DISTRIBUTION_CHANNEL_PATH: release_channel,
            QA_RESTRICT_EXECUTION_PATH: True,
            QA_HOSTED_RUNTIME_PATH: True,
            RELEASE_ENVIRONMENT_PATH: True,
            ADMIN_CONNECTION_PATH: admin_connection,
            SERVING_CONNECTION_PATH: serving_connection,
            EMIT_LOG_METRICS_PATH: True,
            PRODUCTION_ROLE_PATH: production,
        }
    )


__all__ = [
    "ADMIN_CONNECTION_PATH",
    "DISTRIBUTION_BASE_URL_PATH",
    "DISTRIBUTION_CHANNEL_PATH",
    "EMIT_LOG_METRICS_PATH",
    "ENDPOINT_PATHS",
    "HOSTS_API_PATH",
    "HOSTS_APP_PATH",
    "URL_ENDPOINT_PATHS",
    "endpoint_fact_report",
    "MissingEnvironmentFact",
    "PRODUCTION_ROLE_PATH",
    "QA_HOSTED_RUNTIME_PATH",
    "QA_RESTRICT_EXECUTION_PATH",
    "RELEASE_ENVIRONMENT_PATH",
    "SERVING_CONNECTION_PATH",
    "admin_connection_for_environment",
    "decode_settings",
    "declared_bool",
    "declared_text",
    "emits_log_metrics",
    "endpoint_declaration_state",
    "hosted_endpoints",
    "is_hosted_runtime",
    "is_production",
    "is_release_environment",
    "load_environment_settings",
    "production_declared_facts",
    "require_declared_text",
    "restricts_qa_to_self",
    "serving_connection_for_environment",
    "settings_from_projection",
    "target_is_production",
]
