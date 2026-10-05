"""Select and read a named control plane for db-admin connector setup."""

from __future__ import annotations
from pathlib import Path
from yoke_cli.config import machine_config
from yoke_cli.transport import dispatcher as function_dispatcher
from yoke_cli.transport import https as https_transport
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError, _safe_label

CONTROL_PLANE_DATABASE_SQL = "SELECT current_database()"


def _select_control_plane_env(
    env_name: str,
    *,
    control_plane_env: str | None,
    config_path: str | Path | None,
) -> str:
    """Select an explicit HTTPS control plane without ambient fallbacks."""
    selected = _safe_label(
        control_plane_env or env_name,
        what="control-plane environment",
    )
    try:
        connection = machine_config.active_connection(
            config_path,
            explicit_env=selected,
        )
    except (
        machine_config.MachineConfigError,
        contract.MachineConfigContractError,
    ) as exc:
        qualifier = "--control-plane-env " if control_plane_env else ""
        raise DbAdminSetupError(
            f"{qualifier}connection {selected!r} is not configured as an HTTPS "
            "control plane; pass --control-plane-env CONNECTION_ENV naming "
            "an HTTPS connection"
        ) from exc
    if str(connection.get("transport") or "") != contract.TRANSPORT_HTTPS:
        raise DbAdminSetupError(
            f"connection {selected!r} is not HTTPS; pass --control-plane-env "
            "CONNECTION_ENV naming an HTTPS control plane"
        )
    return selected


def _resolve_control_plane_database(
    control_plane_env: str,
    *,
    config_path: str | Path | None,
) -> str:
    """Read the tenant-routed database identity through one named HTTPS env."""
    try:
        connection = https_transport.resolve_https_connection(
            config_path,
            explicit_env=control_plane_env,
        )
    except Exception as exc:  # noqa: BLE001
        raise DbAdminSetupError(
            f"could not resolve HTTPS control plane {control_plane_env!r}: {exc}"
        ) from exc
    if connection is None:
        raise DbAdminSetupError(
            f"connection {control_plane_env!r} is not an HTTPS control plane"
        )
    request = function_dispatcher.build_request(
        function_id="db.read.run",
        target=TargetRef(kind="global"),
        payload={"sql": CONTROL_PLANE_DATABASE_SQL},
    )
    try:
        response = https_transport.relay_https(request, connection)
    except Exception as exc:  # noqa: BLE001
        raise DbAdminSetupError(
            f"control-plane database identity read failed for "
            f"{control_plane_env!r}: "
            f"{_redact_sensitive(str(exc), connection.token)}"
        ) from exc
    if not response.success:
        detail = (
            response.error.message if response.error is not None else "request refused"
        )
        raise DbAdminSetupError(
            f"control-plane database identity read failed for "
            f"{control_plane_env!r}: "
            f"{_redact_sensitive(detail, connection.token)}"
        )
    result = response.result
    expected_keys = {
        "columns",
        "rows",
        "row_count",
        "row_cap",
        "truncated",
        "statement_timeout_ms",
    }
    if set(result) != expected_keys:
        raise DbAdminSetupError(
            "control-plane database identity response has an unexpected shape"
        )
    rows = result.get("rows")
    if (
        result.get("columns") != ["current_database"]
        or result.get("truncated") is not False
        or result.get("row_count") != 1
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], list)
        or len(rows[0]) != 1
        or not isinstance(rows[0][0], str)
        or not rows[0][0].strip()
    ):
        raise DbAdminSetupError(
            "control-plane database identity response must contain exactly "
            "one non-empty current_database value"
        )
    return rows[0][0].strip()


def _redact_sensitive(message: str, secret: str) -> str:
    return message.replace(secret, "<redacted>") if secret else message
