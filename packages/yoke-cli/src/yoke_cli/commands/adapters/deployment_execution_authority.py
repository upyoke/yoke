"""Connection authority for client-local deployment execution.

A run whose target API serves the selected HTTPS control plane cannot be
driven over that connection: the deploy replaces the API that holds the run
state, so it is driven through the paired same-universe database connection.
Execution refuses such a run over HTTPS, and through that database door
refuses every other run, naming the https env that drives it. Creation over
HTTPS stays allowed when this machine has that paired connection, and refuses
without it: a run
created where nobody can drive it occupies its target (and may already have
taken an older run over) with no driver.
"""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from typing import Callable, ContextManager, Mapping, Optional
from urllib.parse import urlsplit

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.direct_database_access import (
    DECLARED_COMMAND_ENV,
    SELF_DEPLOY_EXECUTE_COMMAND,
    USE_HTTPS_ENV,
    direct_database_command,
    paired_https_env,
)
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


def _call(function_id: str, target: TargetRef, payload: dict) -> Mapping[str, object]:
    response = call_dispatcher(function_id=function_id, target=target, payload=payload)
    if not response.success:
        detail = response.error.message if response.error else "request failed"
        raise RuntimeError(f"{function_id} refused: {detail}")
    return response.result or {}


class _RunReadFailed(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _run(run_id: str, relay_env: Optional[str] = None) -> Mapping[str, object]:
    response = call_dispatcher(
        function_id="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"fields": ["project", "target_environment"]},
        relay_env=relay_env,
    )
    if not response.success:
        detail = response.error.message if response.error else "request failed"
        raise _RunReadFailed(
            f"could not resolve deployment execution authority for {run_id}: {detail}",
            code=response.error.code if response.error else "",
        )
    run = (response.result or {}).get("run")
    if not isinstance(run, Mapping):
        raise _RunReadFailed(
            f"could not resolve deployment execution authority for {run_id}: "
            "deployment_runs.get returned no run",
            code="",
        )
    return run


def _self_deploy_refusal(
    target: Callable[[], Optional[tuple[str, str]]],
    subject: str,
    repair_command: str,
    *,
    paired_connection_drives: bool = False,
) -> Optional[str]:
    """Refuse when *target*'s API host serves the selected HTTPS connection.

    *target* answers the run's project and environment, or ``None`` when
    another surface refuses an unresolvable target by name.
    """
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
        resolved = target()
        if resolved is None:
            return None
        project, environment = resolved
        target_host = _target_api_host(
            load_project_renderer_settings_snapshot(project), environment
        )
    except Exception as exc:  # noqa: BLE001 - render a stable CLI refusal
        return str(exc)
    if not target_host or _hostname(target_host) != _hostname(connection.api_url):
        return None
    admin_env = _same_universe_admin_env(connection.env)
    if admin_env and paired_connection_drives:
        return None
    repair = (
        f"rerun with `yoke --env {admin_env} {repair_command}`"
        if admin_env
        else "configure the same-universe owner-only local-postgres connection"
    )
    return (
        f"{subject} targets {target_host}, the API serving the "
        f"selected control plane {connection.env!r}; self-deployment requires "
        f"local database authority so run state remains writable while that "
        f"API is replaced — {repair}"
    )


def execution_connection_error(run_id: str) -> Optional[str]:
    """Refuse only a deploy that would replace its serving control plane."""

    def _target() -> tuple[str, str]:
        run = _run(run_id)
        return str(run.get("project") or ""), str(run.get("target_environment") or "")

    return _self_deploy_refusal(
        _target, f"deployment run {run_id}", f"deployment-runs execute {run_id}"
    )


def door_execution_error(run_id: str, https_env: str) -> Optional[str]:
    """On a ``*-db-admin`` door, allow only a deploy replacing *https_env*'s API.

    Every other run is driven over *https_env*, beside its database. Only a
    definitive answer that the run's target is another API refuses: when
    *https_env* cannot answer the run read at all (unreachable, erroring, or
    answering no run) the door is allowed with a note, because that is the
    self-deploy recovery, re-driving a run whose new API is down or broken.
    """
    from yoke_cli.commands.pulumi_stack_config_loader import (
        load_project_renderer_settings_snapshot,
    )
    from yoke_cli.transport.https import TransportError, resolve_https_connection

    try:
        connection = resolve_https_connection(explicit_env=https_env)
        if connection is None:
            raise TransportError(f"{https_env!r} resolves to no https connection")
        run = _run(run_id, relay_env=https_env)
    except (TransportError, _RunReadFailed) as exc:
        print(
            f"note: {https_env!r} could not answer for {run_id} ({exc}); driving "
            "it through this direct database door as a self-deploy recovery",
            file=sys.stderr,
        )
        return None
    try:
        target_host = _target_api_host(
            load_project_renderer_settings_snapshot(str(run.get("project") or "")),
            str(run.get("target_environment") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - render a stable CLI refusal
        return str(exc)
    if target_host and _hostname(target_host) == _hostname(connection.api_url):
        return None
    return (
        f"{USE_HTTPS_ENV}: deployment run {run_id} does not replace the API "
        f"serving {https_env!r}, so it is driven over that https env beside "
        "its database, not through this direct database door — rerun with "
        f"`yoke --env {https_env} deployment-runs execute {run_id}`"
    )


def self_deploy_door(run_id: str) -> tuple[Optional[str], ContextManager[None]]:
    """The refusal to drive *run_id* through a door, and the scope that holds it.

    Off a paired ``*-db-admin`` door, or inside a process that already holds
    the declaration (a driver started by a declaring parent), there is
    nothing to check and the scope is empty. On a door the run must be a
    self-deploy of the paired API (see :func:`door_execution_error`); the
    scope then declares the door for this process and every child it starts.
    Every driver entry point (the ``watch deploy`` wrapper and the engine
    modules it or ``deployment-runs execute`` runs) enters it, so a driver
    started by an older CLI that declares nothing still holds the door.
    """
    https_env = paired_https_env()
    declared = os.environ.get(DECLARED_COMMAND_ENV) == SELF_DEPLOY_EXECUTE_COMMAND
    if not https_env or declared or not run_id:
        return None, nullcontext()
    refusal = door_execution_error(run_id, https_env)
    if refusal:
        return refusal, nullcontext()
    return None, direct_database_command(SELF_DEPLOY_EXECUTE_COMMAND)


def creation_connection_error(
    command: str,
    *,
    project: Optional[str],
    flow: Optional[str],
    environment: Optional[str],
    item: Optional[str] = None,
) -> Optional[str]:
    """Refuse creating a run this connection could not drive.

    *command* is the operator's ``deployment-runs`` subcommand and arguments,
    repeated in the repair. An item-bound start names its item; the item's
    project and pinned flow fill in what the caller omitted.
    """

    def _target() -> Optional[tuple[str, str]]:
        try:
            return _resolve_creation_target()
        except RuntimeError:
            # Creation itself refuses an unknown item, flow or environment
            # with its own named reason.
            return None

    def _resolve_creation_target() -> tuple[str, str]:
        resolved_project, resolved_flow = project, flow
        if item and not (resolved_project and resolved_flow):
            detail = _call(
                "items.detail.get",
                TargetRef(kind="item", public_ref=item, project_id=project or None),
                {"include": []},
            ).get("item")
            detail = detail if isinstance(detail, Mapping) else {}
            owner = detail.get("project")
            pinned = detail.get("deployment_flow")
            resolved_project = resolved_project or str(
                (owner if isinstance(owner, Mapping) else {}).get("slug") or ""
            )
            resolved_flow = resolved_flow or str(
                (pinned if isinstance(pinned, Mapping) else {}).get("value") or ""
            )
        payload = {"project": resolved_project, "flow": resolved_flow}
        if environment:
            payload["environment"] = environment
        resolved = _call(
            "deployment_runs.resolve_target", TargetRef(kind="global"), payload
        )
        return str(resolved_project), str(resolved.get("target_environment_name") or "")

    refusal = _self_deploy_refusal(
        _target,
        "the run this creates",
        f"deployment-runs {command}",
        paired_connection_drives=True,
    )
    if refusal is None:
        return None
    return (
        f"{refusal}. This machine has no such connection, so a run created "
        "here could not be driven and nothing was created. Report the landing "
        'to steering instead: printf %s "LANDED <ref> <merge sha>" | '
        "yoke say --stdin --steering"
    )


__all__ = [
    "creation_connection_error",
    "door_execution_error",
    "self_deploy_door",
    "execution_connection_error",
]
