"""Which browser profile a QA run used, and whether the page looked signed in.

``raw_result`` already records the commit a freshness source verified. It did
not record whether the daemon opened the operator's authorized profile or a
throwaway context, nor whether the page was an authentication wall. Those
facts belong beside ``code_identity`` so a signed-out capture cannot be read
as a product defect on a signed-in screen.

The profile directory path never enters this record: it lives under capability
secrets and is not QA evidence.
"""

from __future__ import annotations

from typing import Any, Dict

from collections.abc import Mapping

from yoke_contracts.browser_identity import (
    DEFAULT_IDENTITY,
    BrowserIdentity,
    BrowserIdentityError,
    parse_identity_declarations,
    select_identity,
)
from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)

AUTHENTICATION_WALL_LABEL = "authentication_wall"
PROFILE_AUTHORIZED = "authorized"
PROFILE_THROWAWAY = "throwaway"


def load_project_browser_identities(project: str) -> dict[str, BrowserIdentity]:
    """Read the project's declared identities. An absent capability is only default.

    A missing project or an unreadable document refuses by name. Callers apply
    :func:`select_identity` before any browser daemon starts.
    """
    import json

    from yoke_contracts.machine_config.capability_secrets import (
        BROWSER_CONTROL_CAPABILITY,
    )
    from yoke_core.domain.control_plane_transport import ControlPlaneRefused, relay

    try:
        result = relay(
            "projects.capability_settings.get",
            {"project": project, "cap_type": BROWSER_CONTROL_CAPABILITY},
        )
    except ControlPlaneRefused as exc:
        if exc.code != "not_found":
            raise BrowserIdentityError(
                "browser_identity_declarations_unreadable: could not read project "
                f"{project!r} browser-control settings ({exc}). Check the control "
                "plane with `yoke env list`, then retry `yoke qa case run`."
            ) from None
        result = {}
    raw = (result or {}).get("settings_json") or "{}"
    try:
        settings = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError as exc:
        raise BrowserIdentityError(
            "browser_identity_declarations_unreadable: project "
            f"{project!r} browser-control settings are not JSON ({exc}). Repair "
            "them with `yoke projects capability-settings set --cap-type "
            "browser-control`, then retry `yoke qa case run`."
        ) from None
    if not isinstance(settings, dict):
        settings = {}
    return parse_identity_declarations(settings)


def requested_case_identity(method_config: Mapping[str, object] | None) -> str | None:
    """The case's identity name, or None when ``browser_identity`` is omitted."""
    if not isinstance(method_config, Mapping) or "browser_identity" not in method_config:
        return None
    raw = method_config.get("browser_identity")
    return None if raw is None else str(raw)


def resolve_case_identities(
    declared: Mapping[str, BrowserIdentity], rows: list
) -> list[str]:
    """Select each case identity with the shared omission guard."""
    from yoke_core.domain.browser_qa_case_config import parse_case_config

    return [
        select_identity(
            declared,
            requested_case_identity(parse_case_config(row["method_config"])),
        ).name
        for row in rows
    ]


def describe_sign_in(project: str, identity: str = DEFAULT_IDENTITY) -> Dict[str, Any]:
    """Return the profile the daemon would open for one project identity.

    ``authenticated`` starts True only for an authorized profile and is
    flipped False when a step reports an authentication wall. A throwaway
    context is never authenticated. The identity is named so a signed-out
    capture says which persona's sign-in it needed.
    """
    from yoke_cli.config.browser_profile import resolve_authorized_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    described = {"project": project, "identity": identity}
    try:
        profile_path, _note = resolve_authorized_profile(project, identity=identity)
    except ProjectSlugLookupError:
        profile_path = None
    if profile_path is None:
        return {**described, "profile": PROFILE_THROWAWAY, "authenticated": False}
    return {**described, "profile": PROFILE_AUTHORIZED, "authenticated": True}


def authorize_recovery(sign_in: Dict[str, Any], url: str) -> str:
    """Name the unauthorized landing and the operator command that signs in."""
    return (
        f"{EXECUTION_TARGET_UNAUTHORIZED}: this page is an authentication "
        f"wall, not the screen the case asked for. Sign in with "
        f"`yoke browser authorize --project {sign_in.get('project', '')} "
        f"--identity {sign_in.get('identity', DEFAULT_IDENTITY)} --url {url}`."
    )


def observe_authentication_wall(
    sign_in: Dict[str, Any],
    response: Dict[str, Any],
    data: Any,
) -> bool:
    """Record a wall when the daemon reported one. Return whether it did."""
    wall = bool(response.get("authenticationWall"))
    if isinstance(data, dict):
        wall = wall or bool(data.get("authenticationWall"))
    if wall:
        sign_in["authenticated"] = False
    return wall


__all__ = [
    "AUTHENTICATION_WALL_LABEL",
    "PROFILE_AUTHORIZED",
    "PROFILE_THROWAWAY",
    "authorize_recovery",
    "describe_sign_in",
    "load_project_browser_identities",
    "observe_authentication_wall",
    "requested_case_identity",
    "resolve_case_identities",
]
