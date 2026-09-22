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

from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)

AUTHENTICATION_WALL_LABEL = "authentication_wall"
PROFILE_AUTHORIZED = "authorized"
PROFILE_THROWAWAY = "throwaway"


def describe_sign_in(project: str) -> Dict[str, Any]:
    """Return the profile the daemon would open for ``project``.

    ``authenticated`` starts True only for an authorized profile and is
    flipped False when a step reports an authentication wall. A throwaway
    context is never authenticated.
    """
    from yoke_cli.config.browser_profile import resolve_authorized_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        profile_path, _note = resolve_authorized_profile(project)
    except ProjectSlugLookupError:
        return {"profile": PROFILE_THROWAWAY, "authenticated": False}
    if profile_path is None:
        return {"profile": PROFILE_THROWAWAY, "authenticated": False}
    return {"profile": PROFILE_AUTHORIZED, "authenticated": True}


def authorize_recovery(project: str, url: str) -> str:
    """Name the unauthorized landing and the operator command that signs in."""
    return (
        f"{EXECUTION_TARGET_UNAUTHORIZED}: this page is an authentication "
        f"wall, not the screen the case asked for. Sign in with "
        f"`yoke browser authorize --project {project} --url {url}`."
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
    "observe_authentication_wall",
]
