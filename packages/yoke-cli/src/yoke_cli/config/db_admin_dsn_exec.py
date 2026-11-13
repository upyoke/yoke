"""Run one subprocess with a db-admin profile's DSN in a caller-named variable.

The profile is a machine-local ``local-postgres`` connection written by
``yoke dev db-admin setup``; it reads its owner-only ``dsn_file`` and the SSH
forward is brought up by the connected-env readiness path. The DSN lives only in this process and
in the one child's environment: it is never printed, logged, written to disk,
or emitted as an event, and every refusal is redacted before it is shown.
"""

from __future__ import annotations

import os
import re
import subprocess
from importlib import import_module
from typing import Any, Callable, Sequence

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract

DSN_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SETUP_RECIPE = (
    "`yoke dev db-admin setup ENV --project PROJECT [--database MODEL] --yes`"
)


class DbAdminExecRefusal(RuntimeError):
    """A diagnosed refusal: named reason, redacted detail, recovery step."""

    def __init__(
        self, reason: str, message: str, recovery: str, *, exit_code: int = 1
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.recovery = recovery
        self.exit_code = exit_code

    def report_lines(self) -> tuple[str, str]:
        return (f"error: {self.reason}: {self}", f"  recovery: {self.recovery}")


def run(
    admin_env: str,
    dsn_var: str,
    command: Sequence[str],
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    """Run *command* once with the profile DSN in ``dsn_var``; return its code."""
    if not DSN_VAR_PATTERN.match(dsn_var or ""):
        raise DbAdminExecRefusal(
            "invalid_dsn_var",
            f"{dsn_var!r} is not an environment variable name",
            "pass --dsn-var NAME using letters, digits, and underscores",
            exit_code=2,
        )
    if not command:
        raise DbAdminExecRefusal(
            "missing_command",
            "no command follows --",
            "append `-- <command> [args...]`",
            exit_code=2,
        )
    _require_postgres_profile(admin_env)
    dsn = _resolve_dsn(admin_env)
    child_env = dict(os.environ)
    child_env[dsn_var] = dsn
    coordination = _engine(
        lambda: import_module("yoke_core.domain.connected_env_tunnel_coordination")
    )
    with coordination.use_lease_for_active_tunnel(
        f"db-admin exec for {admin_env}", environment=admin_env
    ):
        try:
            completed = runner(list(command), env=child_env)
        except OSError as exc:
            raise DbAdminExecRefusal(
                "command_not_runnable",
                f"{command[0]!r} could not be started ({exc.strerror or exc})",
                "check the command name and that it is on PATH",
                exit_code=127,
            ) from None
    return int(completed.returncode)


def _require_postgres_profile(admin_env: str) -> None:
    try:
        connection = machine_config.active_connection(None, explicit_env=admin_env)
    except (machine_config.MachineConfigError, contract.MachineConfigContractError):
        raise DbAdminExecRefusal(
            "profile_not_configured",
            f"connection {admin_env!r} is not configured on this machine",
            f"list connections with `yoke env list`; create the profile with {SETUP_RECIPE}",
        ) from None
    transport = str(connection.get("transport") or "")
    if transport not in contract.POSTGRES_TRANSPORTS:
        raise DbAdminExecRefusal(
            "profile_not_postgres",
            f"connection {admin_env!r} uses transport {transport!r}, not a "
            "local Postgres profile",
            f"name a *-db-admin connection from `yoke env list`, or create one with {SETUP_RECIPE}",
        )


def _resolve_dsn(admin_env: str) -> str:
    selected = _engine(
        lambda: import_module("yoke_core.domain.connected_env_selected_readiness")
    )
    connector = _engine(
        lambda: import_module("yoke_core.domain.connected_env_readiness_connector")
    )
    try:
        authority = selected.activate_selected_postgres(admin_env)
    except selected.SelectedPostgresError as exc:
        raise DbAdminExecRefusal(
            "profile_unusable",
            connector.redact(str(exc)),
            f"re-create the profile with {SETUP_RECIPE}",
        ) from None
    except connector.ConnectedEnvUnavailable as exc:
        raise _unreachable(admin_env, connector.redact(str(exc))) from None
    if not authority.readiness.ok:
        raise _unreachable(admin_env, connector.redact(authority.readiness.message))
    return str(authority.dsn)


def _unreachable(admin_env: str, detail: str) -> DbAdminExecRefusal:
    return DbAdminExecRefusal(
        "database_unreachable",
        f"the database behind {admin_env!r} is not reachable: {detail}",
        "check network/VPN access to the profile's SSH bastion "
        "(connections.<env>.postgres.tunnel.bastion in ~/.yoke/config.json), "
        "then rerun",
    )


def _engine(load: Callable[[], Any]) -> Any:
    try:
        return load()
    except ModuleNotFoundError as exc:
        raise DbAdminExecRefusal(
            "engine_unavailable",
            f"the yoke-core engine module {exc.name} is not importable here",
            "reinstall Yoke or run from a Yoke source checkout",
        ) from None


__all__ = ["DSN_VAR_PATTERN", "DbAdminExecRefusal", "run"]
