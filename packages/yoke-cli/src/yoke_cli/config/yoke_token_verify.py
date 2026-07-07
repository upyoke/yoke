"""Yoke API token verification helpers for onboarding."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.api_urls import (
    AUTH_IDENTITY_PATH,
    FUNCTIONS_CALL_PATH,
    FUNCTIONS_REGISTRY_PATH,
    join_api_url,
)
from yoke_cli.config import secrets as machine_secrets

_TIMEOUT_S = 20.0
_IDENTITY_PATH = AUTH_IDENTITY_PATH
_REGISTRY_PATH = FUNCTIONS_REGISTRY_PATH
_CALL_PATH = FUNCTIONS_CALL_PATH

# Highest-to-lowest authority; the connect screen shows a single role per
# org/project, picking the most-privileged the actor holds there.
_ROLE_PRECEDENCE = ["admin", "owner", "operator", "viewer"]


class YokeTokenVerificationError(RuntimeError):
    """A Yoke API token check failed."""


def read_token_source(
    *,
    token: str | None = None,
    token_file: str | Path | None = None,
    source_kind: str = "prompt",
) -> str:
    """Resolve a prompt/file token without leaking the secret in errors."""
    if token_file is not None:
        try:
            return machine_secrets.read_secret_file(token_file, "token")
        except machine_secrets.MachineSecretError as exc:
            raise YokeTokenVerificationError(str(exc)) from exc
    secret = (token or "").strip()
    if not secret:
        label = "file" if source_kind == "token_file" else source_kind
        raise YokeTokenVerificationError(f"Yoke token from {label} is empty")
    return secret


def verify(api_url: str, token: str) -> dict[str, Any]:
    """Verify a Yoke token and return actor/org/project evidence."""
    base = api_url.rstrip("/")
    identity_url = join_api_url(base, _IDENTITY_PATH)
    try:
        identity = _request_json(identity_url, token)
    except _EndpointUnavailable:
        return _verify_with_function_probe(base, token)
    if not isinstance(identity, Mapping):
        raise YokeTokenVerificationError(
            "Yoke identity check returned an invalid response"
        )
    result = dict(identity)
    result.setdefault("checked", True)
    result.setdefault("ok", True)
    result.setdefault("status", "verified")
    result.setdefault("source", "identity")
    result["url"] = identity_url
    return result


def success_message(verification: Mapping[str, Any]) -> str:
    """Plain-language success copy for the onboarding confirmation screen.

    The actor / org / project specifics render as their own bullet lines just
    below this headline, so the headline itself stays one clean line.
    """
    return "Success! You've authenticated with Yoke."


def missing_org_project_access_message(
    verification: Mapping[str, Any],
) -> str | None:
    """Return actionable copy when a valid token has no usable Yoke scope."""
    if _list_of_mappings(verification.get("orgs")):
        return None
    if _list_of_mappings(verification.get("projects")):
        return None
    return (
        "Yoke token is valid, but it does not include access to any Yoke "
        "organization or project."
    )


def missing_org_project_access_detail_lines() -> list[str]:
    return [
        "Ask a Yoke admin to add this actor or token to an organization or project.",
        "Then choose Try again or use a different token.",
    ]


def detail_lines(verification: Mapping[str, Any]) -> list[str]:
    """Short evidence lines for the wizard success screen."""
    lines: list[str] = []
    actor_name = _actor_name(verification)
    if actor_name:
        lines.append(f"Actor: {actor_name}")
    orgs = _list_of_mappings(verification.get("orgs"))
    if orgs:
        label = "Organizations" if len(orgs) > 1 else "Organization"
        lines.append(f"{label}: {_org_label(orgs)}")
    projects = _list_of_mappings(verification.get("projects"))
    if projects:
        lines.append(f"Projects: {_project_label(projects)}")
    return lines


def _verify_with_function_probe(base_url: str, token: str) -> dict[str, Any]:
    projects: list[dict[str, Any]] = []
    call_url = join_api_url(base_url, _CALL_PATH)
    registry_url = join_api_url(base_url, _REGISTRY_PATH)
    try:
        payload = _request_json(call_url, token, body=_projects_envelope())
        if isinstance(payload, Mapping) and payload.get("success") is True:
            result = payload.get("result")
            if isinstance(result, Mapping):
                rows = result.get("rows")
                if isinstance(rows, list):
                    projects = [
                        {
                            "id": row.get("id"),
                            "slug": row.get("slug"),
                            "name": row.get("name"),
                            "roles": [],
                        }
                        for row in rows
                        if isinstance(row, Mapping)
                    ]
    except _EndpointUnavailable:
        pass
    registry_count = None
    registry = _request_json(registry_url, token)
    if isinstance(registry, list):
        registry_count = len(registry)
    elif isinstance(registry, Mapping) and isinstance(registry.get("functions"), list):
        registry_count = len(registry["functions"])
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "function_probe",
        "url": registry_url,
        "registry_count": registry_count,
        "orgs": [],
        "projects": projects,
    }


def _request_json(
    url: str,
    token: str,
    *,
    body: Mapping[str, Any] | None = None,
) -> Any:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and url.endswith(_IDENTITY_PATH):
            raise _EndpointUnavailable from exc
        if url.endswith(_CALL_PATH) and exc.code != 401:
            raise _EndpointUnavailable from exc
        raise YokeTokenVerificationError(_http_error_message(exc, url)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise YokeTokenVerificationError(
            f"Yoke token check failed against {url}: {exc}"
        ) from exc
    try:
        return json.loads(raw) if raw else None
    except ValueError as exc:
        raise YokeTokenVerificationError(
            f"Yoke token check returned invalid JSON from {url}"
        ) from exc


def _http_error_message(exc: urllib.error.HTTPError, url: str) -> str:
    detail = ""
    try:
        raw = exc.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            detail = str(error.get("message") or "")
        elif payload.get("detail"):
            detail = str(payload["detail"])
    suffix = f": {detail}" if detail else ""
    return f"Yoke token check failed: {url} returned HTTP {exc.code}{suffix}"


def _projects_envelope() -> dict[str, Any]:
    return {
        "function": "projects.list",
        "version": "v1",
        "actor": {"actor_id": None, "session_id": ""},
        "target": {"kind": "global"},
        "payload": {},
        "preconditions": {},
        "options": {},
    }


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _actor_name(verification: Mapping[str, Any]) -> str:
    """Resolve a human label for the actor, never a bare numeric id.

    Order: the server-resolved display name (actor.label, from actor_labels),
    then the token's own name, then a clearly-marked id fallback.
    """
    actor = verification.get("actor")
    if not isinstance(actor, Mapping):
        return ""
    label = str(actor.get("label") or "").strip()
    if label:
        return label
    token = verification.get("token")
    if isinstance(token, Mapping):
        token_name = str(token.get("name") or "").strip()
        if token_name:
            return token_name
    actor_id = actor.get("id")
    if actor_id is not None:
        return f"actor #{actor_id}"
    return ""


def _org_label(orgs: list[Mapping[str, Any]]) -> str:
    entries = [
        _named_role_entry(org.get("name") or org.get("slug"), org.get("roles"))
        for org in orgs
    ]
    return _bounded_entries(entries)


def _project_label(projects: list[Mapping[str, Any]]) -> str:
    entries = [
        _named_role_entry(
            project.get("name") or project.get("slug"), project.get("roles")
        )
        for project in projects
    ]
    return _bounded_entries(entries)


def _named_role_entry(name: Any, roles: Any) -> str:
    """Render one "Name (role)" entry, dropping the suffix when no role."""
    label = str(name or "").strip()
    role = _top_role(roles)
    if label and role:
        return f"{label} ({role})"
    return label


def _top_role(roles: Any) -> str:
    """The single highest-precedence role name from a role list."""
    values = {str(role).strip() for role in (roles or []) if str(role).strip()}
    if not values:
        return ""
    for role in _ROLE_PRECEDENCE:
        if role in values:
            return role
    return sorted(values)[0]


def _bounded_entries(entries: list[str]) -> str:
    """List entries in full when few; else the first few plus "and N more".

    Matches the "…, and N more" summary the GitHub token screen uses
    (onboard_wizard_flow_github) so every onboard list truncates the same way.
    """
    entries = [entry for entry in entries if entry]
    if not entries:
        return ""
    limit = 4
    if len(entries) <= limit + 1:
        return ", ".join(entries)
    return f"{', '.join(entries[:limit])}, and {len(entries) - limit} more"


class _EndpointUnavailable(Exception):
    """A richer endpoint is unavailable, so the verifier can fall back."""


__all__ = [
    "YokeTokenVerificationError",
    "detail_lines",
    "missing_org_project_access_detail_lines",
    "missing_org_project_access_message",
    "read_token_source",
    "success_message",
    "verify",
]
