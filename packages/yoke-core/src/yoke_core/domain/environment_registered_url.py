"""The registered environment url column, and how to write or repair it.

``environments.url`` is the only origin authorized to answer for a
persistent target. Create and update write it; identity readers already
select it. An empty value is a configuration gap, and every refusal that
names the gap also names the command that fills it.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Sequence

from yoke_core.domain.served_revision_probe import origin_of

URL_PLACEHOLDER = "https://<origin>"


def environment_url_repair_command(
    project: str, environment: str, *, url: str = URL_PLACEHOLDER
) -> str:
    """The exact CLI that writes *url* onto the named environment row."""
    return (
        f"yoke projects environment update --project {project} "
        f"--environment {environment} --url {url}"
    )


def registered_url_error(url: str) -> str:
    """Why *url* cannot be stored as an origin, or "" if it can."""
    raw = str(url or "").strip()
    if not raw:
        return "url is required"
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "url must be an http(s) origin (scheme and host)"
    return ""


def normalize_registered_url(url: str) -> str:
    """Scheme and host only; a path on the value is not stored."""
    error = registered_url_error(url)
    if error:
        raise ValueError(error)
    return origin_of(url.strip())


def missing_registered_url_message(project: str, environment: str) -> str:
    """Refusal that names the repair command, not just the missing column."""
    return (
        f"environment {environment!r} has no registered url, so the "
        "served-revision path this project configures has no origin "
        "authorized to answer for it; register it before deploying: "
        f"{environment_url_repair_command(project, environment)}"
    )


def environments_missing_url(
    conn: Any, project_id: int, names: Sequence[str]
) -> tuple[str, ...]:
    """QA-target environment names that have no registered origin."""
    from yoke_core.domain.deployment_target_identity_config import (
        environment_urls,
    )

    wanted = [name for name in names if name]
    urls = environment_urls(conn, int(project_id), wanted)
    return tuple(name for name in wanted if name not in urls)


__all__ = [
    "URL_PLACEHOLDER",
    "environment_url_repair_command",
    "environments_missing_url",
    "missing_registered_url_message",
    "normalize_registered_url",
    "registered_url_error",
]
