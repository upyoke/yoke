"""Box mode for ``yoke dev db-admin setup``: Postgres on the environment's box.

Every environment runs Postgres in its box VM on a Mac host
(``environments.settings.database.location`` is ``box``). Its profile forwards the local port
over the Yoke-owned SSH hop (:mod:`yoke_cli.config.db_admin_box_hop`) to the
VM's ``127.0.0.1:5432`` and reads the DSN from an owner-only machine-local
file the operator provisions from the environment's custody files. Nothing is
looked up in Pulumi or AWS Secrets Manager, and the DSN is never read into a
report or printed.
"""

from __future__ import annotations

from importlib import import_module
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import secret_files as machine_secrets
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_cli.config import db_admin_box_hop as box_hop
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError
from yoke_cli.config.db_admin_setup_report import _path_ref

BOX_AUTHORITY_KIND = "box_postgres"
BOX_REMOTE_HOST = "127.0.0.1"


def dsn_file_path(label: str) -> Path:
    """Owner-only machine secret file that holds the box profile's DSN."""
    try:
        return machine_secrets.secret_path_no_create(label, "dsn")
    except machine_secrets.MachineSecretError as exc:
        raise DbAdminSetupError(f"--secret-name {label!r}: {exc}") from exc


def plan(
    env: Any,
    *,
    postgres: dict[str, Any],
    database_name: str,
    dsn_path: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Point the tunnel at the box's own Postgres; return authority and steps."""
    postgres["tunnel"].update(box_hop.tunnel_fields(env))
    postgres["tunnel"]["remote_host"] = BOX_REMOTE_HOST
    authority = {
        "kind": BOX_AUTHORITY_KIND,
        "location": {
            "origin_host": str(env.origin_host),
            "database_name": database_name,
        },
    }
    steps = [
        {
            "action": "resolve-deploy-environment",
            "target": f"{env.project}/{env.env_name}",
        },
        *box_hop.plan_steps(env),
        {
            "action": "forward-to-box-postgres",
            "target": (
                f"{box_hop.alias(env.env_name)} via {box_hop.mac_host(env)} -> "
                f"{BOX_REMOTE_HOST}:{postgres['tunnel']['remote_port']}"
            ),
        },
        {"action": "configure-dsn-file-credential", "target": _path_ref(dsn_path)},
    ]
    return authority, steps


def apply(
    env: Any,
    dsn_path: Path,
    *,
    admin_env: str,
    local_host: str,
    local_port: int,
    database_name: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Check the DSN file, then make the hop work; return source and hop report."""
    source = credential_source(
        dsn_path,
        admin_env=admin_env,
        local_host=local_host,
        local_port=local_port,
        database_name=database_name,
    )
    return source, box_hop.ensure(env)


def credential_source(
    dsn_path: Path,
    *,
    admin_env: str,
    local_host: str,
    local_port: int,
    database_name: str,
) -> dict[str, str]:
    """Validate the provisioned DSN before any SSH or config writes."""
    try:
        dsn = machine_secrets.read_secret_file(dsn_path, f"{admin_env} DSN")
    except (machine_secrets.MachineSecretError, UnicodeError):
        raise DbAdminSetupError(
            f"box_dsn_file_unavailable: write a readable {admin_env} DSN "
            f"(postgresql://USER:PASSWORD@{local_host}:{local_port}/{database_name}) "
            f"from the environment's custody file to {_path_ref(dsn_path)} with "
            "mode 600, then rerun"
        ) from None
    _validate_dsn_endpoint(dsn, admin_env, local_host, local_port)
    return {"kind": contract.CREDENTIAL_KIND_DSN_FILE, "path": str(dsn_path)}


def _validate_dsn_endpoint(
    dsn: str, admin_env: str, local_host: str, local_port: int,
) -> None:
    selected = f"{local_host}:{local_port}"
    repair = f"provision a DSN with the loopback endpoint {selected}, then rerun"
    try:
        psycopg = import_module("psycopg")
    except ImportError:
        raise DbAdminSetupError(compose_refusal(
            "box_dsn_parser_unavailable: db-admin setup requires Psycopg",
            recovery="reinstall Yoke with the local engine and rerun setup",
        )) from None
    try:
        parameters = psycopg.conninfo.conninfo_to_dict(dsn)
    except (psycopg.ProgrammingError, UnicodeError):
        raise DbAdminSetupError(compose_refusal(
            f"box_dsn_invalid: {admin_env} has an invalid PostgreSQL DSN",
            evaluated=f"selected SSH forward {selected}",
            recovery=repair,
        )) from None

    host = parameters.get("host")
    hostaddr = parameters.get("hostaddr")
    loopback = _loopback_host(hostaddr or host)
    port_text = parameters.get("port") or ""
    if (
        parameters.get("service")
        or not loopback
        or (host and not _loopback_host(host))
        or (hostaddr and loopback == "localhost")
    ):
        raise DbAdminSetupError(compose_refusal(
            f"box_dsn_endpoint_mismatch: {admin_env} DSN must specify a single loopback endpoint",
            evaluated=f"selected SSH forward {selected}",
            recovery=repair,
        ))
    port = 0
    if len(port_text) <= 5 and port_text.isascii() and port_text.isdecimal():
        port = int(port_text)
    if port != local_port:
        dsn_endpoint = f"{loopback} with no valid explicit port"
        if 1 <= port <= 65535:
            dsn_endpoint = f"{loopback}:{port}"
            repair = f"rerun with --local-port {port} to use the DSN endpoint, or {repair}"
        raise DbAdminSetupError(compose_refusal(
            f"box_dsn_endpoint_mismatch: {admin_env} DSN selects {dsn_endpoint}",
            evaluated=f"selected SSH forward {selected}",
            recovery=repair,
        ))


def _loopback_host(host: str | None) -> str | None:
    if not host:
        return None
    if host.lower() in {"localhost", "localhost."}:
        return "localhost"
    try:
        address = ip_address(host)
    except ValueError:
        return None
    if str(address) in {"127.0.0.1", "::1"}:
        return f"[{address}]" if address.version == 6 else str(address)
    return None


__all__ = [
    "BOX_AUTHORITY_KIND",
    "BOX_REMOTE_HOST",
    "apply",
    "credential_source",
    "dsn_file_path",
    "plan",
]
