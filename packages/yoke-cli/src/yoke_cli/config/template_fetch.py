"""Product-client side of ``yoke templates list`` / ``fetch``.

Templates are product-shipped code-tree content (no DB, no org data), so
the active connection's transport decides where they come from, mirroring
:mod:`yoke_cli.project_install.transport`:

* ``transport: "https"`` — ``GET {api_url}/v1/templates[/{name}]`` with
  the machine bearer credential; the env's server serves its own tree.
* non-prod ``transport: "local-postgres"`` — this install serves its own
  code tree in-process via :mod:`yoke_core.domain.template_bundle`.

Prod-flagged local-postgres connections stay operator-only and are
refused.
"""

from __future__ import annotations

import importlib
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from yoke_cli.config import machine_config
from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    error_detail,
    request_json,
    safe_diagnostic_text,
)
from yoke_cli.transport.response_limits import (
    BUNDLE_JSON_RESPONSE_LIMIT_BYTES,
    DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS,
)
from yoke_contracts.api_urls import join_api_url
from yoke_contracts.machine_config.schema import (
    MachineConfigContractError,
    POSTGRES_TRANSPORTS,
    connection_is_prod,
)
from yoke_contracts.template_bundle import (
    TEMPLATE_BUNDLE_SCHEMA,
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_PRODUCT,
    TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
    TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM,
    TEMPLATES_API_PATH,
)

_FETCH_TIMEOUT_S = DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS


class TemplateFetchError(RuntimeError):
    """The template operation cannot complete; message names the repair."""


def resolve_listing(
    config_path: str | Path | None = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Resolve the template listing via the active connection's transport."""
    local_env = _local_env(config_path)
    if local_env is not None:
        return (
            _serve_local(lambda bundle_module: bundle_module.list_templates()),
            _local_source(local_env),
        )
    connection = _https_connection(config_path)
    payload = _fetch_json_https(connection, TEMPLATES_API_PATH)
    templates = payload.get("templates")
    if not isinstance(templates, list):
        raise TemplateFetchError(
            f"{connection.api_url}{TEMPLATES_API_PATH} returned no "
            "'templates' list; the active env may predate this surface "
            "(check `yoke status`)"
        )
    return templates, connection.api_url


def resolve_bundle(
    name: str,
    config_path: str | Path | None = None,
    *,
    include_source_dev_admin: bool = False,
) -> Tuple[Dict[str, Any], str]:
    """Resolve one template's bundle via the active connection's transport."""
    local_env = _local_env(config_path)
    if local_env is not None:
        bundle = _serve_local(
            lambda bundle_module: bundle_module.build_template_bundle(
                name,
                include_source_dev_admin=include_source_dev_admin,
            )
        )
        return bundle, _local_source(local_env)
    connection = _https_connection(config_path)
    bundle = _fetch_json_https(
        connection,
        _bundle_route(name, include_source_dev_admin=include_source_dev_admin),
        template=name,
    )
    _validate_bundle(bundle)
    _assert_template_fetch_allowed(
        bundle,
        include_source_dev_admin=include_source_dev_admin,
    )
    return bundle, connection.api_url


def fetch(
    name: str,
    dest: str | Path | None = None,
    *,
    only: Optional[str] = None,
    force: bool = False,
    config_path: str | Path | None = None,
    include_source_dev_admin: bool = False,
) -> Dict[str, Any]:
    """Fetch template ``name`` and write its files under ``dest``."""
    bundle, source = resolve_bundle(
        name,
        config_path,
        include_source_dev_admin=include_source_dev_admin,
    )
    _assert_template_fetch_allowed(
        bundle,
        include_source_dev_admin=include_source_dev_admin,
    )
    dest_root = (Path(dest) if dest else Path(os.getcwd())).expanduser().resolve()
    entries: List[Dict[str, str]] = bundle["files"]
    prefix = (only or "").strip()
    if prefix:
        entries = [e for e in entries if e["path"].startswith(prefix)]
    _assert_safe_paths(e["path"] for e in entries)

    written: List[str] = []
    skipped_existing: List[str] = []
    dest_root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        target = dest_root / entry["path"]
        if target.exists() and not force:
            skipped_existing.append(entry["path"])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry["content"], encoding="utf-8")
        written.append(entry["path"])
    return {
        "operation": "fetch",
        "template": bundle["template"],
        "dest": str(dest_root),
        "source": source,
        "yoke_version": bundle["yoke_version"],
        TEMPLATE_PRODUCT_BOUNDARY_FIELD: _template_product_boundary(bundle),
        "only": prefix or None,
        "files_written": written,
        "files_skipped_existing": skipped_existing,
        "binary_files_skipped": int(bundle.get("binary_files_skipped") or 0),
    }


# Lazily imported name for the in-process builder; the https path never
# needs the engine package installed.
_TEMPLATE_BUNDLE_MODULE = "yoke_core.domain.template_bundle"


def _local_env(config_path: str | Path | None) -> Optional[str]:
    """The active non-prod local-postgres env label, or ``None`` for https.

    A prod-flagged local-postgres connection stays operator-only, so the
    product surface refuses it rather than serving from this install's
    code tree. A missing/unusable machine config returns ``None`` so the
    https resolver owns the setup-refusal message.
    """
    try:
        connection = machine_config.active_connection(config_path)
    except MachineConfigContractError:
        return None
    if str(connection.get("transport") or "") not in POSTGRES_TRANSPORTS:
        return None
    env_name = str(connection.get("env") or "<env>")
    if connection_is_prod(connection):
        raise TemplateFetchError(
            f"env {env_name!r} is a prod-marked local-postgres connection, "
            "which stays operator-only; use an HTTPS product-client env or "
            "a non-prod local env (`yoke env use <env>`)"
        )
    return env_name


def _local_source(env_name: str) -> str:
    """Report label for a listing/bundle served from this install's tree."""
    return f"local-postgres:{env_name}"


def _serve_local(operation):
    """Run one template-bundle operation against this install's code tree."""
    try:
        bundle_module = importlib.import_module(_TEMPLATE_BUNDLE_MODULE)
    except ModuleNotFoundError as exc:
        raise TemplateFetchError(
            "the yoke-core engine package is not importable, so this "
            "install cannot serve templates from its own code tree; "
            "reinstall Yoke or switch to an HTTPS product-client env"
        ) from exc
    try:
        return operation(bundle_module)
    except bundle_module.TemplateBundleError as exc:
        raise TemplateFetchError(str(exc)) from exc


def _https_connection(config_path: str | Path | None):
    try:
        connection = resolve_https_connection(config_path)
    except TransportError as exc:
        raise TemplateFetchError(str(exc)) from exc
    if connection is None:
        raise TemplateFetchError(
            "the active env is neither an HTTPS product-client connection "
            "nor a non-prod local install (https envs GET the templates "
            "from the env's server; local envs serve them in-process from "
            "this install's code tree); run `yoke status`, switch with "
            "`yoke env use <env>`, or configure one with `yoke connection set`"
        )
    return connection


def _assert_safe_paths(paths: Iterable[str]) -> None:
    """Refuse bundle paths that could escape the destination dir."""
    for raw in paths:
        path = Path(raw)
        if not raw or path.is_absolute() or ".." in path.parts:
            raise TemplateFetchError(
                f"bundle names an unsafe path {raw!r}: paths must be "
                "dest-relative and must not traverse '..'"
            )


def _bundle_route(name: str, *, include_source_dev_admin: bool) -> str:
    quoted = urllib.parse.quote(str(name), safe="")
    route = f"{TEMPLATES_API_PATH}/{quoted}"
    if not include_source_dev_admin:
        return route
    query = urllib.parse.urlencode({TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM: "true"})
    return f"{route}?{query}"


def _fetch_json_https(
    connection, route: str, template: Optional[str] = None
) -> Dict[str, Any]:
    url = join_api_url(connection.api_url, route)
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
        detail = error_detail(exc.payload)
        safe_url = safe_diagnostic_text(url, sensitive_values=(connection.token,))
        if exc.status == 404 and template is not None:
            raise TemplateFetchError(
                f"template {template!r} is unknown to the active env "
                f"({safe_url} returned 404); list the served templates with "
                "`yoke templates list`"
            ) from None
        if exc.status == 403 and detail:
            raise TemplateFetchError(detail) from exc
        raise TemplateFetchError(
            f"{safe_url} returned HTTP {exc.status}; verify the active env and "
            "credential with `yoke status`"
        ) from None
    except BoundedJsonHttpError as exc:
        raise TemplateFetchError(
            "could not fetch "
            f"{safe_diagnostic_text(url, sensitive_values=(connection.token,))}: "
            f"{exc}; verify the active env with "
            "`yoke status`"
        ) from None
    payload = response.payload
    if not isinstance(payload, dict):
        raise TemplateFetchError(
            f"{safe_diagnostic_text(url)} returned a non-object body"
        )
    return payload


def _validate_bundle(bundle: Dict[str, Any]) -> None:
    schema = bundle.get("bundle_schema")
    if schema != TEMPLATE_BUNDLE_SCHEMA:
        raise TemplateFetchError(
            f"bundle_schema {schema!r} is not the supported "
            f"{TEMPLATE_BUNDLE_SCHEMA}; upgrade this CLI "
            "(rerun the public installer) to match the env"
        )
    files = bundle.get("files")
    if not isinstance(files, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("content"), str)
        for e in files
    ):
        raise TemplateFetchError(
            "bundle 'files' must be a list of {path, content} objects"
        )


def _template_product_boundary(bundle: Dict[str, Any]) -> str:
    boundary = bundle.get(TEMPLATE_PRODUCT_BOUNDARY_FIELD)
    if not boundary:
        return TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
    return str(boundary)


def _assert_template_fetch_allowed(
    bundle: Dict[str, Any],
    *,
    include_source_dev_admin: bool,
) -> None:
    boundary = _template_product_boundary(bundle)
    if (
        boundary == TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
        and not include_source_dev_admin
    ):
        raise TemplateFetchError(
            f"template {bundle.get('template')!r} is source-dev/admin material; "
            "rerun with `yoke templates fetch --source-dev-admin` only from "
            "an operator-approved source-dev/admin flow"
        )


__all__ = [
    "TemplateFetchError",
    "fetch",
    "resolve_bundle",
    "resolve_listing",
]
