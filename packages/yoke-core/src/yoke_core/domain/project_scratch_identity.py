"""Resolve project and machine owners into stable scratch namespaces.

Connected callers converge on numeric project ids. Offline callers retain
their explicit slug. Projectless captures use authority and optional actor
namespaces without querying the control plane.
"""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from yoke_core.domain.control_plane_transport import local_connection_or_none, relay
from yoke_core.domain.project_scratch_roots import (
    MACHINE_SCOPE_DIRNAME,
    ScratchRootResolutionError,
)
from yoke_core.domain.project_scratch_segments import safe_segment


def _control_plane_selected() -> bool:
    """Inspect existing authority bindings without connecting or loading secrets."""
    from yoke_core.domain import db_backend, yoke_connected_env
    from yoke_core.domain.cloud_db_secret_dsn import env_binding_selected

    return bool(
        db_backend.pg_dsn_is_bound()
        or os.environ.get(db_backend.PG_DSN_ENV)
        or os.environ.get(db_backend.PG_DSN_FILE_ENV)
        or env_binding_selected()
        or yoke_connected_env.load_active() is not None
    )


def resolve_project_namespace(reference: str) -> str:
    """Return a numeric id when connected, or the caller's safe offline slug."""
    ref = str(reference).strip()
    if ref.isdigit() and int(ref) > 0:
        return str(int(ref))
    if not _control_plane_selected():
        return safe_segment(ref)

    from yoke_core.domain import db_helpers
    from yoke_core.domain.project_identity import resolve_project_id

    conn = local_connection_or_none(db_helpers.connect)
    if conn is not None:
        with conn:
            return str(resolve_project_id(conn, ref))
    result = relay("projects.get", {"project": ref, "field": "id"})
    value = result.get("value")
    if str(value).isdigit() and int(value) > 0:
        return str(int(value))
    raise LookupError(
        f"project {ref!r} did not resolve to an id for scratch storage; "
        "pass --project with an accessible numeric project id"
    )


_machine_owner: ContextVar[int | None] = ContextVar(
    "scratch_machine_owner", default=None
)


@contextmanager
def scratch_machine_owner(actor_id: int) -> Iterator[None]:
    """Bind the authenticated actor for machine-scoped server scratch."""
    token = _machine_owner.set(actor_id)
    try:
        yield
    finally:
        _machine_owner.reset(token)


def machine_scope_namespace() -> tuple[str, ...]:
    """Return one directory for the selected authority, without connecting."""
    from yoke_core.domain import db_backend, yoke_connected_env

    env = yoke_connected_env.load_active()
    authority = (
        env.environment
        if env
        else ("local" if db_backend.pg_dsn_is_bound() else "offline")
    )
    # Encode separators and the actor delimiter without merging distinct names.
    key = quote(authority, safe="").replace("-", "%2D").replace(".", "%2E")
    # Named connections are distinct from the unnamed local/offline modes.
    mode = "env-" if env else ""
    return (MACHINE_SCOPE_DIRNAME + mode + safe_segment(key),)


def resolve_scratch_namespace(
    project: str | None, *, bound_project: str | None
) -> tuple[str, ...]:
    """Prefer explicit project bindings, then actor ownership, then local context."""
    from yoke_contracts.project_defaults import default_project_for_directory

    selected = project or bound_project
    if not selected:
        owner = _machine_owner.get()
        if owner is not None:
            return (f"{machine_scope_namespace()[0]}-actor-{owner}",)
        selected = os.environ.get("YOKE_PROJECT", "").strip()
        selected = selected or default_project_for_directory(Path.cwd())
    if not selected:
        return machine_scope_namespace()
    namespace = safe_segment(resolve_project_namespace(selected))
    if namespace.startswith(MACHINE_SCOPE_DIRNAME):
        raise ScratchRootResolutionError(
            f"scratch project namespace {namespace!r} is reserved for machine scope; "
            "rename the offline project reference"
        )
    return (namespace,)
