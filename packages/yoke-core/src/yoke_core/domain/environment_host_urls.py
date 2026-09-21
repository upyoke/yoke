"""Write-time http(s) URL convention for endpoint facts consumed as URLs.

``hosts.app``, ``hosts.api``, and ``distribution.base_url`` are URLs with a
scheme. A write that stores a scheme-less host refuses here rather than
leaving two readers to disagree later.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from yoke_core.domain.refusal_recovery import compose_refusal

_URL_SET_RECOVERY = (
    "set it via: yoke projects environment-settings merge "
    "--project <project> --environment <environment> --set {path}=https://<host>"
)


def http_url_error(value: Any) -> str:
    """Why *value* is not an http(s) URL, or '' if it is absent or valid."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return "must be an http(s) URL (scheme and host)"
    text = value.strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "must be an http(s) URL (scheme and host)"
    return ""


def refuse_url_value(path: str, value: Any) -> None:
    """Refuse a non-empty assignment that is not an http(s) URL."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return
    problem = http_url_error(value if isinstance(value, str) else str(value))
    if isinstance(value, str) and not problem:
        return
    text = value.strip() if isinstance(value, str) else value
    raise ValueError(
        compose_refusal(
            f"{path} {problem or 'must be an http(s) URL (scheme and host)'}: "
            f"{text!r}",
            recovery=_URL_SET_RECOVERY.format(path=path),
        )
    )


def refuse_invalid_endpoint_url_assignments(
    assignments: Mapping[str, Any],
) -> None:
    """Refuse a settings write that stores a scheme-less hosts.* URL fact."""
    from yoke_core.domain.environment_declared_facts import (
        DISTRIBUTION_BASE_URL_PATH,
        URL_ENDPOINT_PATHS,
    )

    for path, value in assignments.items():
        if path in URL_ENDPOINT_PATHS:
            refuse_url_value(path, value)
        elif path == "hosts" and isinstance(value, Mapping):
            for key in ("app", "api"):
                if key in value:
                    refuse_url_value(f"hosts.{key}", value[key])
        elif (
            path == "distribution"
            and isinstance(value, Mapping)
            and "base_url" in value
        ):
            refuse_url_value(DISTRIBUTION_BASE_URL_PATH, value["base_url"])


def split_host_url(value: Any) -> tuple[str, str]:
    """Return ``(hostname, origin)`` for a declared ``hosts.*`` URL."""
    from yoke_core.domain.environment_declared_facts import HOSTS_API_PATH

    text = value.strip() if isinstance(value, str) else ""
    problem = http_url_error(value)
    if problem or not text:
        raise ValueError(
            compose_refusal(
                f"{HOSTS_API_PATH} {problem or 'is required'}: {value!r}",
                recovery=_URL_SET_RECOVERY.format(path=HOSTS_API_PATH),
            )
        )
    parsed = urlsplit(text)
    return parsed.hostname or parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"


__all__ = [
    "http_url_error",
    "refuse_invalid_endpoint_url_assignments",
    "refuse_url_value",
    "split_host_url",
]
