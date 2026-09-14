"""Connection authority for client-local deployment execution."""

from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import urlsplit

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.transport.dispatcher import call_dispatcher


def _same_universe_admin_env(env: str) -> str:
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import same_universe_db_admin_env

        return same_universe_db_admin_env(machine_config.load_config(), env)
    except Exception:  # noqa: BLE001 - only affects recovery teaching
        return ""


def _hostname(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    return str(parsed.hostname or "").rstrip(".").lower()


def _target_api_host(snapshot: Mapping[str, object], environment: str) -> str:
    renderer = snapshot.get("renderer_settings")
    if not isinstance(renderer, Mapping):
        return ""
    environments = renderer.get("environments")
    if not isinstance(environments, list):
        return ""
    for candidate in environments:
        if not isinstance(candidate, Mapping):
            continue
        if str(candidate.get("name") or "") != environment:
            continue
        settings = candidate.get("settings")
        if not isinstance(settings, Mapping):
            return ""
        hosts = settings.get("hosts")
        return str(hosts.get("api") or "") if isinstance(hosts, Mapping) else ""
    return ""


def _run(run_id: str) -> Mapping[str, object]:
    response = call_dispatcher(
        function_id="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={},
    )
    if not response.success:
        detail = response.error.message if response.error else "request failed"
        raise RuntimeError(
            f"could not resolve deployment execution authority for {run_id}: {detail}"
        )
    run = (response.result or {}).get("run")
    if not isinstance(run, Mapping):
        raise RuntimeError(
            f"could not resolve deployment execution authority for {run_id}: "
            "deployment_runs.get returned no run"
        )
    return run


def execution_connection_error(run_id: str) -> Optional[str]:
    """Refuse only a deploy that would replace its serving control plane."""
    from yoke_cli.commands.pulumi_stack_config_loader import (
        load_project_renderer_settings_snapshot,
    )
    from yoke_cli.transport.https import TransportError, resolve_https_connection

    try:
        connection = resolve_https_connection()
    except TransportError as exc:
        return f"deployment execution cannot use the selected HTTPS connection: {exc}"
    if connection is None:
        return None
    try:
        run = _run(run_id)
        project = str(run.get("project") or "")
        environment = str(run.get("target_environment") or "")
        target_host = _target_api_host(
            load_project_renderer_settings_snapshot(project), environment
        )
    except Exception as exc:  # noqa: BLE001 - render a stable CLI refusal
        return str(exc)
    if not target_host or _hostname(target_host) != _hostname(connection.api_url):
        return None
    admin_env = _same_universe_admin_env(connection.env)
    repair = (
        f"rerun with `yoke --env {admin_env} deployment-runs execute {run_id}`"
        if admin_env
        else "configure the same-universe owner-only local-postgres connection"
    )
    return (
        f"deployment run {run_id} targets {target_host}, the API serving the "
        f"selected control plane {connection.env!r}; self-deployment requires "
        f"local database authority so run state remains writable while that "
        f"API is replaced — {repair}"
    )


__all__ = ["execution_connection_error"]
