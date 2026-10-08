"""Freeze the Yoke release a deployed candidate pins into its QA target.

A distribution channel such as ``latest`` is a mutable pointer that other
releases move, so a QA install that follows it can test a release the
candidate never pinned. The environment's desired-pin settings leaf moves too:
a later release records its own pin there. The only authority that cannot
move is the deployed commit itself, so a project whose deployments pin a Yoke
release names the file holding that pin in its ``release_pin`` capability
(``candidate_pin_file``), and the frozen deployment target reads it at the
exact commit the run delivered for that project. It carries the pin as
``endpoints.release_version`` so install steps pass it to the installer
(``--version`` / ``YOKE_VERSION``) through the bound installer origin.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from yoke_contracts.release_pin import CANDIDATE_PIN_FILE_KEY, RELEASE_PIN_CAPABILITY
from yoke_core.domain import db_backend
from yoke_core.domain.project_file_at_commit import (
    ProjectFileAbsent,
    ProjectFileUnreadable,
    read_project_file,
)
from yoke_core.domain.release_pin_capability import candidate_pin_file

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


def _pin_file(conn: Any, project_id: int) -> str:
    settings = _capability_settings(conn, project_id)
    if settings is None:
        return ""
    try:
        return candidate_pin_file(settings)
    except ValueError as exc:
        raise ValueError(
            f"deployment_qa_release_pin_invalid: {exc}; repair it with "
            "`yoke projects capability-settings merge` before starting QA"
        ) from exc


def pinned_release_endpoints(
    conn: Any, run_id: str, project_id: int, endpoints: dict[str, Any]
) -> dict[str, Any]:
    """``endpoints`` plus the release the run's deployed commit pins, if declared."""
    path = _pin_file(conn, project_id)
    if not path:
        return endpoints
    from yoke_core.domain.deployment_run_project_sources import run_delivered_sha

    sha = run_delivered_sha(conn, run_id, int(project_id))
    if not sha:
        raise ValueError(
            f"deployment_qa_release_pin_source_missing: run {run_id} recorded no "
            f"deployed commit for project {project_id}, so the release it pins "
            "cannot be read; repair the run's recorded sources before starting QA"
        )
    try:
        raw = read_project_file(conn, int(project_id), sha, path)
    except ProjectFileAbsent as exc:
        raise ValueError(
            f"deployment_qa_release_pin_missing: {exc}; commit the pinned release "
            f"to {path} or correct {RELEASE_PIN_CAPABILITY}.{CANDIDATE_PIN_FILE_KEY}"
            ", then redeploy"
        ) from exc
    except ProjectFileUnreadable as exc:
        raise ValueError(
            f"deployment_qa_release_pin_unreadable: cannot read {path} at the "
            f"deployed commit {sha} ({exc}); register this project's checkout "
            "(`yoke project register`) or repair its GitHub binding, then re-run "
            "the QA stage"
        ) from exc
    version = raw.decode("utf-8", errors="replace").strip()
    if not version or len(version.split()) != 1:
        raise ValueError(
            f"deployment_qa_release_pin_missing: {path} at {sha} does not hold "
            "one release version; correct the pin file and redeploy"
        )
    installer_base_url = str(endpoints.get("installer_base_url") or "")
    if installer_base_url:
        require_published(installer_base_url, version)
    return {**endpoints, RELEASE_VERSION_KEY: version}


__all__ = [
    "RELEASE_VERSION_KEY",
    "pinned_release_endpoints",
    "release_records_url",
    "require_published",
]
