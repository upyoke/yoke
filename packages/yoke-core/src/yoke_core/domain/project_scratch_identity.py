"""Resolve caller project references into stable scratch namespaces.

Connected callers converge on numeric project ids. Offline callers retain
their explicit slug so local captures never require a control plane.
"""

import os

from yoke_core.domain.control_plane_transport import local_connection_or_none, relay
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
