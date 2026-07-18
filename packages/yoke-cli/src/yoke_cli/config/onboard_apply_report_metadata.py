"""Secret-safe metadata for durable onboarding apply reports."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Mapping

from yoke_cli.config import install_binding, onboard_github_snapshot


RESUME_COMMAND = "yoke onboard"

_AUTH_HEADER_RE = re.compile(
    r"(Authorization:\s*)(Bearer|token)\s+[-._A-Za-z0-9]+",
    re.IGNORECASE,
)
_TOKEN_ASSIGN_RE = re.compile(r"(\btoken\s*[=:]\s*)[^&\s,;]+", re.IGNORECASE)
_URL_USERINFO_RE = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)([^@\s/]+)@([^/\s]+)",
    re.IGNORECASE,
)


def sanitize_text(value: str) -> str:
    redacted = _AUTH_HEADER_RE.sub(r"\1<redacted>", value)
    redacted = _TOKEN_ASSIGN_RE.sub(r"\1<redacted>", redacted)
    return _URL_USERINFO_RE.sub(_redact_url_userinfo, redacted)


def _redact_url_userinfo(match: re.Match[str]) -> str:
    scheme, userinfo, host = match.groups()
    username, separator, _secret = userinfo.partition(":")
    if separator:
        return f"{scheme}{username}:<redacted>@{host}"
    return f"{scheme}<redacted>@{host}"


def safe_remote_url(value: Any) -> str:
    """Strip URL credentials and query secrets before durable persistence."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            port = parsed.port
            netloc = f"{host}:{port}" if port is not None else host
            return urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    "",
                    "",
                )
            )
    except (TypeError, ValueError):
        pass
    return sanitize_text(raw)


def package_version() -> str:
    return install_binding.distribution_version(source_value="source") or "unknown"


def target_github_repo(kwargs: Mapping[str, Any]) -> str:
    owner = str(kwargs.get("project_publish_owner") or "")
    name = str(kwargs.get("project_publish_repo_name") or "")
    repo = str(kwargs.get("project_github_repo") or "")
    if owner and name:
        return f"{owner}/{name}"
    publish = kwargs.get("project_publish")
    publish_owner = str(getattr(publish, "owner", "") or "")
    publish_name = str(getattr(publish, "name", "") or "")
    if publish_owner and publish_name:
        return f"{publish_owner}/{publish_name}"
    return repo


def new_target_hint(kwargs: Mapping[str, Any]) -> str:
    """Return recovery guidance that never claims checkout deletion."""

    checkout = str(kwargs.get("project_checkout") or "").strip()
    if checkout:
        return (
            f"Preserve {checkout} and re-run with a different folder: {RESUME_COMMAND}"
        )
    return f"Re-run to redo setup: {RESUME_COMMAND}"


def credential_sources(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "yoke": {
            "kind": str(kwargs.get("token_source_kind") or "argument"),
            "path": str(kwargs.get("token_file") or ""),
        },
        "github_app": {
            "machine": onboard_github_snapshot.authorization_source(kwargs),
            "project": onboard_github_snapshot.binding(kwargs),
        },
    }


__all__ = [
    "RESUME_COMMAND",
    "credential_sources",
    "new_target_hint",
    "package_version",
    "safe_remote_url",
    "sanitize_text",
    "target_github_repo",
]
