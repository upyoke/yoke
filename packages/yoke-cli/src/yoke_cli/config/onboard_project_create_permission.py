"""Review probe: may the signed-in person create a project on the chosen server?

``projects.create`` is org-scoped and refuses without ``project.create``. Setup
asks the selected connection's ``profile.get`` first, so Review can withhold
Apply before any folder is written. The answer is ``None`` (unknown) whenever
the server cannot say: no token, a failed read, or an older server whose
``profile.get`` has no ``project_create_orgs``. A local universe is skipped:
its operator owns the org.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from yoke_contracts.onboard_destinations import DESTINATION_LOCAL

from yoke_cli.config.existing_project_http import (
    ExistingProjectLookupError,
    call_function,
)


def probe_for(
    result: Any, read_token: Callable[[], str | None]
) -> Callable[[str | None], bool | None] | None:
    """Return the live probe for ``result``'s connection, or None to skip it."""
    if getattr(result, "destination", None) == DESTINATION_LOCAL:
        return None
    api_url = str(getattr(result, "api_url", None) or "").strip()
    if not api_url:
        return None

    def _allowed(org: str | None) -> bool | None:
        token = read_token()
        if not token:
            return None
        try:
            response = call_function(
                api_url=api_url, token=token, function="profile.get", payload={}
            )
        except ExistingProjectLookupError:
            return None
        return allowed_from_profile(response, org)

    return _allowed


def allowed_from_profile(response: Mapping[str, Any], org: str | None) -> bool | None:
    """Decide from a ``profile.get`` response envelope; None when it can't say."""
    if not response.get("success"):
        return None
    payload = response.get("result")
    orgs = payload.get("project_create_orgs") if isinstance(payload, Mapping) else None
    if not isinstance(orgs, list):
        return None
    entries = [entry for entry in orgs if isinstance(entry, Mapping)]
    if org:
        return any(org in (entry.get("slug"), entry.get("name")) for entry in entries)
    return any(entry.get("default") is True for entry in entries)


__all__ = ["allowed_from_profile", "probe_for"]
