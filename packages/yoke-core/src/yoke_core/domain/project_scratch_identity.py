"""Resolve caller project references into numeric scratch namespaces.

Numeric checkout and request identities already name the namespace. Slugs
need the connected control plane's identity lookup; they never become paths.
"""

from yoke_core.domain.control_plane_transport import local_connection_or_none, relay


def canonical_project_id(reference: str) -> str:
    """Return the project id for an explicit, environmental, or checkout ref."""
    ref = str(reference).strip()
    if ref.isdigit() and int(ref) > 0:
        return str(int(ref))

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
