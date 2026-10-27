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

from contextvars import ContextVar
from typing import Any, Dict
from urllib.parse import urlsplit

from collections.abc import Mapping

from yoke_contracts.browser_identity import (
    DEFAULT_IDENTITY,
    case_browser_identity,
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
BROWSER_SIGN_IN_SETUP = "browser_sign_in_setup"
_GOOGLE_ACCOUNT: ContextVar[str] = ContextVar(
    "browser_qa_google_account",
    default="",
)


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


def resolve_case_identities(
    declared: Mapping[str, BrowserIdentity], rows: list
) -> list[str]:
    """Select each case identity, defaulting omitted identities to default."""
    from yoke_core.domain.browser_qa_case_config import parse_case_config

    return [
        select_identity(
            declared,
            case_browser_identity(parse_case_config(row["method_config"])),
        ).name
        for row in rows
    ]


def recorded_google_account(declared: BrowserIdentity | None) -> str:
    """The Google account this identity's profile is signed in as, if recorded."""
    if declared is None:
        return ""
    for site in declared.sites:
        host = urlsplit(site.origin).hostname or ""
        if host == "accounts.google.com" and site.account:
            return site.account
    accounts = [site.account for site in declared.sites if site.account]
    if len(accounts) == 1:
        return accounts[0]
    return ""


def current_google_account() -> str:
    """Account the latest :func:`describe_sign_in` told the daemon to click."""
    return _GOOGLE_ACCOUNT.get()


def describe_sign_in(
    project: str,
    identity: str = DEFAULT_IDENTITY,
    declared: BrowserIdentity | None = None,
) -> Dict[str, Any]:
    """Return the profile the daemon would open for one project identity.

    ``authenticated`` stays false until a step observes the app's signed-in
    page. A profile directory is not that observation. A throwaway context
    is never authenticated. The identity is named so a signed-out capture
    says which persona's sign-in it needed.
    """
    from yoke_cli.config.browser_profile import resolve_authorized_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    _GOOGLE_ACCOUNT.set(recorded_google_account(declared))
    described = {"project": project, "identity": identity}
    try:
        profile_path, _note = resolve_authorized_profile(project, identity=identity)
    except ProjectSlugLookupError:
        profile_path = None
    if profile_path is None:
        return {**described, "profile": PROFILE_THROWAWAY, "authenticated": False}
    return {**described, "profile": PROFILE_AUTHORIZED, "authenticated": False}


def authorize_recovery(sign_in: Dict[str, Any], url: str) -> str:
    """Name the unauthorized landing and the operator command that signs in."""
    return (
        f"{EXECUTION_TARGET_UNAUTHORIZED}: this page is an authentication "
        f"wall, not the screen the case asked for. Sign in with "
        f"`yoke browser authorize --project {sign_in.get('project', '')} "
        f"--identity {sign_in.get('identity', DEFAULT_IDENTITY)} --url {url}`."
    )


def setup_recovery(sign_in: Dict[str, Any], detail: str) -> str:
    """Name a Google sign-in the case could not finish, and how to repair it."""
    project = sign_in.get("project", "")
    identity = sign_in.get("identity", DEFAULT_IDENTITY)
    reason = detail.strip() or "the profile is not signed in to the app"
    return (
        f"{BROWSER_SIGN_IN_SETUP}: {reason} "
        f"Sign in with `yoke browser authorize --project {project} "
        f"--identity {identity}`, then retry the case. "
        "Never enter credentials in the case."
    )


def observe_authentication_wall(
    sign_in: Dict[str, Any],
    response: Dict[str, Any],
    data: Any,
) -> bool:
    """Record whether this step saw a sign-in page or the signed-in app.

    ``authenticated`` becomes true only for an authorized profile whose step
    succeeded on a page the daemon observed was not a sign-in page.
    """
    payload = data if isinstance(data, dict) else {}
    wall = bool(response.get("authenticationWall")) or bool(
        payload.get("authenticationWall")
    )
    sign_in_page = (
        wall or bool(payload.get("signInPage")) or bool(response.get("signInPage"))
    )
    if sign_in_page:
        sign_in["authenticated"] = False
    elif (
        payload.get("signInPage") is False
        and sign_in.get("profile") == PROFILE_AUTHORIZED
        and payload.get("success", response.get("success", True))
    ):
        sign_in["authenticated"] = True
    return wall


__all__ = [
    "AUTHENTICATION_WALL_LABEL",
    "BROWSER_SIGN_IN_SETUP",
    "PROFILE_AUTHORIZED",
    "PROFILE_THROWAWAY",
    "authorize_recovery",
    "current_google_account",
    "describe_sign_in",
    "load_project_browser_identities",
    "observe_authentication_wall",
    "recorded_google_account",
    "resolve_case_identities",
    "setup_recovery",
]
