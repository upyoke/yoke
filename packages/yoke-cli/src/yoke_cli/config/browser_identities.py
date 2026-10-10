"""Read a project's declared browser sign-in identities from the control plane.

Declarations are nonsecret data in the project's ``browser-control``
capability settings (shape: ``yoke_contracts.browser_identity``). They are
read through the registered ``projects.capability_settings.get`` function, so
a Test Machine with no checkout of the project reads the same declarations as
the operator's own machine. A project with no ``browser-control`` capability
declares nothing and has only the ``default`` identity, which behaves exactly
as the single per-project profile always did.
"""

from __future__ import annotations

import json

from yoke_contracts.browser_identity import (
    BrowserIdentity,
    BrowserIdentityError,
    parse_identity_declarations,
    select_identity,
)
from yoke_contracts.machine_config.capability_secrets import (
    BROWSER_CONTROL_CAPABILITY,
)


def declared_identities(
    project_key: str, *, session_id: str | None = None
) -> dict[str, BrowserIdentity]:
    """Return every identity the project declares, ``default`` included."""
    from yoke_contracts.api.function_call import TargetRef

    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project_key, "cap_type": BROWSER_CONTROL_CAPABILITY},
        actor=build_actor(session_id=session_id),
    )
    if not response.success:
        if response.error is not None and response.error.code == "not_found":
            return parse_identity_declarations({})
        detail = (
            response.error.message
            if response.error is not None
            else "the control plane returned no settings"
        )
        raise BrowserIdentityError(
            "browser_identity_declarations_unreadable: could not read project "
            f"{project_key!r} browser-control settings: {detail}. Check the "
            "control plane with `yoke env list`, then retry."
        )
    raw = (response.result or {}).get("settings_json") or "{}"
    try:
        settings = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise BrowserIdentityError(
            "browser_identity_declarations_unreadable: project "
            f"{project_key!r} browser-control settings are not JSON ({exc}). "
            "Repair them with `yoke projects capability-settings set`."
        ) from None
    return parse_identity_declarations(settings if isinstance(settings, dict) else {})


def resolve_identity(
    project_key: str, identity: str | None, *, session_id: str | None = None
) -> BrowserIdentity:
    """Return one declared identity, refusing an undeclared name by name."""
    return select_identity(
        declared_identities(project_key, session_id=session_id), identity
    )


__all__ = ["declared_identities", "resolve_identity"]
