"""Resolve a project reference to the slug machine-local storage is keyed by.

Machine-local paths under ``~/.yoke/secrets`` name a project by its slug, but a
command may be handed either the slug an operator typed (``--project yoke``) or
the numeric project id the checkout default answers with. Storage keyed by
whatever it was handed splits one project across two directories, so every path
that names a project on disk resolves the reference through here first.

The id is resolved by the registered ``projects.get`` read, which relays over
https and dispatches in-process on a local connection, so the answer is the
control plane's regardless of transport.
"""

from __future__ import annotations


class ProjectSlugLookupError(RuntimeError):
    """A project reference did not resolve to a project slug."""


def resolve_project_slug(reference: str, *, session_id: str | None = None) -> str:
    """Return the slug for a project reference, or raise naming the recovery."""
    ref = str(reference or "").strip()
    if not ref:
        raise ProjectSlugLookupError(
            "a project reference is required. Pass --project <slug>, or run "
            "from a checkout this machine maps to a project."
        )

    from yoke_contracts.api.function_call import TargetRef

    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.get",
        target=TargetRef(kind="global"),
        payload={"project": ref, "field": "slug"},
        actor=build_actor(session_id=session_id),
    )
    if response.success:
        value = (response.result or {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    detail = (
        response.error.message
        if response.error is not None
        else "the control plane returned no slug"
    )
    raise ProjectSlugLookupError(
        f"project {ref!r} did not resolve to a slug: {detail}. Check the "
        "control plane with `yoke env list`, or name the project by slug "
        "(for example `--project yoke`)."
    )


__all__ = ["ProjectSlugLookupError", "resolve_project_slug"]
