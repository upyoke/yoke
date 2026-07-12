"""Bundle resolution for ``yoke project install``."""

from __future__ import annotations

import contextlib
import importlib
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
    safe_diagnostic_text,
)
from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_cli.transport.response_limits import (
    BUNDLE_JSON_RESPONSE_LIMIT_BYTES,
    DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS,
)
from yoke_contracts.api_urls import join_api_url
from yoke_contracts.machine_config.schema import (
    CREDENTIAL_KIND_DSN_FILE,
    CREDENTIAL_KIND_ENV,
    MachineConfigContractError,
    POSTGRES_TRANSPORTS,
    connection_is_prod,
)

_FETCH_TIMEOUT_S = DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS
_BUNDLE_PATH_TEMPLATE = "/v1/projects/{project_id}/install-bundle"


def resolve_bundle(
    project_id: int,
    *,
    explicit_env: Optional[str],
    config_path: str | Path | None,
) -> Tuple[Dict[str, Any], str]:
    """Resolve the project install bundle for the active transport."""
    try:
        connection = machine_config.active_connection(
            config_path,
            explicit_env=explicit_env,
        )
    except MachineConfigContractError as exc:
        raise ProjectInstallError(str(exc)) from exc

    if str(connection.get("transport") or "") in POSTGRES_TRANSPORTS:
        return (
            _fetch_bundle_local_postgres(project_id, connection, config_path),
            f"local-postgres:{connection.get('env') or '<env>'}",
        )

    try:
        connection = resolve_https_connection(
            config_path,
            explicit_env=explicit_env,
        )
    except (MachineConfigContractError, TransportError) as exc:
        raise ProjectInstallError(str(exc)) from exc
    if connection is None:
        raise ProjectInstallError(
            "the active env is not an HTTPS product-client connection; "
            "run `yoke status`, switch with `yoke env use <https-env>`, "
            "or use the explicit Yoke source-dev/admin setup branch"
        )
    return _fetch_bundle_https(connection, project_id), connection.api_url


def _fetch_bundle_local_postgres(
    project_id: int,
    connection: Mapping[str, Any],
    config_path: str | Path | None,
) -> Dict[str, Any]:
    env_name = str(connection.get("env") or "<env>")
    if connection_is_prod(connection):
        raise ProjectInstallError(
            f"env {env_name!r} is a prod-marked local-postgres connection; "
            "`yoke project install` only builds local bundles from non-prod "
            "local mode. Use an HTTPS product-client env or an audited "
            "source-dev/admin flow for prod database authority."
        )
    try:
        db_backend = importlib.import_module("yoke_core.domain.db_backend")
        connect = importlib.import_module("yoke_core.domain.db_helpers").connect
        build_bundle = importlib.import_module(
            "yoke_core.domain.install_bundle"
        ).build_bundle
    except ModuleNotFoundError as exc:
        raise ProjectInstallError(
            "the yoke-core engine package is not importable, so the "
            "local-postgres install bundle cannot be rendered; reinstall "
            "Yoke or switch to an HTTPS product-client env"
        ) from exc
    with _local_postgres_env(
        connection,
        config_path,
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    ):
        conn = connect()
        try:
            return build_bundle(project_id, conn)
        finally:
            conn.close()


@contextlib.contextmanager
def _local_postgres_env(
    connection: Mapping[str, Any],
    config_path: str | Path | None,
    *,
    dsn_env: str,
    dsn_file_env: str,
) -> Iterator[None]:
    source = connection.get("credential_source")
    source = source if isinstance(source, Mapping) else {}
    kind = str(source.get("kind") or "")
    updates: dict[str, str] = {}
    removals: set[str] = set()
    if kind == CREDENTIAL_KIND_DSN_FILE:
        raw_path = str(source.get("path") or "").strip()
        if not raw_path:
            raise ProjectInstallError(
                "local-postgres credential_source.kind 'dsn_file' requires path"
            )
        dsn_path = _credential_path(raw_path, config_path)
        if not dsn_path.is_file():
            raise ProjectInstallError(f"local-postgres DSN file is missing: {dsn_path}")
        updates[dsn_file_env] = str(dsn_path)
        removals.add(dsn_env)
    elif kind == CREDENTIAL_KIND_ENV:
        name = str(source.get("name") or dsn_env).strip()
        dsn = os.environ.get(name, "").strip()
        if not dsn:
            raise ProjectInstallError(
                f"local-postgres credential env var is missing: {name}"
            )
        updates[dsn_env] = dsn
        removals.add(dsn_file_env)
    else:
        raise ProjectInstallError(
            "local-postgres project install requires credential_source.kind "
            f"'dsn_file' or 'env' (got {kind or 'nothing'})"
        )
    with _patched_env(updates, removals):
        yield


def _credential_path(raw_path: str, config_path: str | Path | None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return machine_config.config_path(config_path).parent / path


@contextlib.contextmanager
def _patched_env(
    updates: Mapping[str, str],
    removals: set[str],
) -> Iterator[None]:
    prior = {name: os.environ.get(name) for name in set(updates) | removals}
    try:
        for name in removals:
            os.environ.pop(name, None)
        os.environ.update(updates)
        yield
    finally:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _fetch_bundle_https(connection, project_id: int) -> Dict[str, Any]:
    url = join_api_url(
        connection.api_url,
        _BUNDLE_PATH_TEMPLATE.format(project_id=project_id),
    )
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {connection.token}"}
    )
    try:
        response = request_json(
            request,
            timeout_seconds=_FETCH_TIMEOUT_S,
            replay_safe=True,
            allow_loopback_http=True,
            response_limit_bytes=BUNDLE_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(connection.token,),
            opener=urllib.request.urlopen,
        )
    except BoundedJsonHttpStatusError as exc:
        safe_url = safe_diagnostic_text(url, sensitive_values=(connection.token,))
        if exc.status == 404:
            raise ProjectInstallError(
                f"project id {project_id} is unknown to the active env "
                f"({safe_url} returned 404); check the id with `yoke status` "
                "or pass the right --project-id"
            ) from None
        raise ProjectInstallError(
            f"{safe_url} returned HTTP {exc.status}; verify the active env and "
            "credential with `yoke status`"
        ) from None
    except BoundedJsonHttpError as exc:
        raise ProjectInstallError(
            "could not fetch the install bundle from "
            f"{safe_diagnostic_text(url, sensitive_values=(connection.token,))}: "
            f"{exc}; verify "
            "the active env with `yoke status`"
        ) from None
    payload = response.payload
    if not isinstance(payload, dict):
        raise ProjectInstallError(
            f"{safe_diagnostic_text(url)} returned a non-object bundle body"
        )
    return payload


__all__ = ["resolve_bundle"]
