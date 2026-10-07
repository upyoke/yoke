"""Freeze the Yoke release a deployed candidate pins into its QA target.

A distribution channel such as ``latest`` is a mutable pointer that other
releases move, so a QA install that follows it can test a release the
candidate never pinned. A project whose deployments pin a Yoke release
declares the ``release_pin`` capability; its ``desired_pin_path`` names the
environment-settings leaf the deployment records. The frozen deployment
target carries that pin as ``endpoints.release_version`` so install steps
pass it to the installer (``--version`` / ``YOKE_VERSION``) through the
bound installer origin.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from yoke_contracts.release_pin import RELEASE_PIN_CAPABILITY
from yoke_core.domain import db_backend
from yoke_core.domain.qa_execution_environment_target import (
    _decode,
    _generic_endpoints,
)
from yoke_core.domain.release_pin_capability import route_for_environment
from yoke_core.domain.settings_cas import read_key_path

RELEASE_VERSION_KEY = "release_version"
_FETCH_TIMEOUT_SECONDS = 15


def _capability_settings(conn: Any, project_id: int) -> dict[str, Any] | None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT settings FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (int(project_id), RELEASE_PIN_CAPABILITY),
    ).fetchone()
    if row is None:
        return None
    raw = row["settings"] if hasattr(row, "keys") else row[0]
    try:
        settings = json.loads(str(raw or "{}"))
    except ValueError:
        settings = None
    if not isinstance(settings, dict):
        raise ValueError(
            f"deployment_qa_release_pin_invalid: project {project_id} has a "
            f"malformed {RELEASE_PIN_CAPABILITY!r} capability; repair it with "
            "`yoke projects capability-settings set` before starting QA"
        )
    return settings


def release_records_url(installer_base_url: str, version: str) -> str:
    """The immutable per-release record the distribution publishes."""
    from yoke_core.tools.release_artifacts import (
        DIST_ROOT,
        RELEASE_RECORDS_FILENAME,
        RELEASES_DIR,
    )

    return (
        f"{installer_base_url.rstrip('/')}/{DIST_ROOT}/{RELEASES_DIR}/"
        f"{quote(version, safe='')}/{RELEASE_RECORDS_FILENAME}"
    )


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:
        return response.read()


def require_published(installer_base_url: str, version: str) -> None:
    """Refuse a pinned release the bound installer origin cannot install."""
    url = release_records_url(installer_base_url, version)
    recovery = (
        f"publish Yoke {version} to {installer_base_url} (or correct the "
        "candidate's release pin and redeploy), then re-run the QA stage"
    )
    try:
        payload = json.loads(_fetch(url))
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"deployment_qa_release_unpublished: Yoke {version} pinned by the "
            f"deployed candidate is not published at {installer_base_url} "
            f"(HTTP {exc.code} for {url}); {recovery}"
        ) from exc
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"deployment_qa_release_unverified: could not read {url} to confirm "
            f"Yoke {version} is published ({exc}); restore access to the "
            f"installer origin, or {recovery}"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError(
            f"deployment_qa_release_unpublished: {url} lists no published "
            f"wheels; {recovery}"
        )


def pinned_release_endpoints(
    conn: Any, project_id: int, environment: str, row: Mapping[str, Any]
) -> dict[str, Any]:
    """Environment endpoints plus the release the deployed candidate pins."""
    settings = _decode(row["settings"])
    endpoints = _generic_endpoints(row, settings)
    capability = _capability_settings(conn, project_id)
    if capability is None:
        return endpoints
    try:
        route = route_for_environment(capability, environment)
    except ValueError as exc:
        raise ValueError(
            f"deployment_qa_release_pin_invalid: {exc}; repair the project's "
            f"{RELEASE_PIN_CAPABILITY!r} capability before starting QA"
        ) from exc
    pin = read_key_path(settings, route.desired_pin_path)
    version = pin.strip() if isinstance(pin, str) else ""
    if not version:
        raise ValueError(
            f"deployment_qa_release_pin_missing: environment {environment!r} "
            f"records no release pin at {route.desired_pin_path!r}; the "
            "deployment must record it (`yoke release-pin record --project P "
            f"--environment {environment} --pin VERSION`) before QA can install "
            "the candidate's pinned release"
        )
    installer_base_url = str(endpoints.get("installer_base_url") or "")
    if installer_base_url:
        require_published(installer_base_url, version)
    endpoints[RELEASE_VERSION_KEY] = version
    return endpoints


__all__ = [
    "RELEASE_VERSION_KEY",
    "pinned_release_endpoints",
    "release_records_url",
    "require_published",
]
