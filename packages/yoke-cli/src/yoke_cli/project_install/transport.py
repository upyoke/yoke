"""HTTPS bundle resolution for ``yoke project install``."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_contracts.api_urls import join_api_url
from yoke_contracts.machine_config.schema import MachineConfigContractError

_FETCH_TIMEOUT_S = 30.0
_BUNDLE_PATH_TEMPLATE = "/v1/projects/{project_id}/install-bundle"


def resolve_bundle(
    project_id: int,
    *,
    explicit_env: Optional[str],
    config_path: str | Path | None,
) -> Tuple[Dict[str, Any], str]:
    """Resolve the bundle through the product-client HTTPS transport."""
    try:
        machine_config.product_connection(config_path, explicit_env=explicit_env)
        connection = resolve_https_connection(
            config_path, explicit_env=explicit_env,
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


def _fetch_bundle_https(connection, project_id: int) -> Dict[str, Any]:
    url = join_api_url(
        connection.api_url,
        _BUNDLE_PATH_TEMPLATE.format(project_id=project_id),
    )
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {connection.token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ProjectInstallError(
                f"project id {project_id} is unknown to the active env "
                f"({url} returned 404); check the id with `yoke status` "
                "or pass the right --project-id"
            ) from exc
        raise ProjectInstallError(
            f"{url} returned HTTP {exc.code}; verify the active env and "
            "credential with `yoke status`"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ProjectInstallError(
            f"could not fetch the install bundle from {url}: {exc}; verify "
            "the active env with `yoke status`"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError(f"{url} returned a non-object bundle body")
    return payload


__all__ = ["resolve_bundle"]
