"""Keep project write grants on project notes and admin authority on unscoped notes."""

from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.handlers.ouroboros_roster_scope import includes_unscoped
from yoke_core.domain.function_unresolved_project import permission_error_response
from yoke_core.domain.yoke_function_permission_types import DispatchPermission

LIFECYCLE_FUNCTIONS = frozenset({"ouroboros.entry.mark_reviewed", "ouroboros.entry.mark_archived"})


def feedback_lifecycle_permission(conn, entry, request, permission_key):
    if entry.function_id not in LIFECYCLE_FUNCTIONS:
        return None
    payload = request.payload or {}
    unscoped_entry = False
    try:
        entry_id = int(payload.get("entry_id"))
        row = conn.execute(f"SELECT project_id FROM ouroboros_entries WHERE id={placeholder(conn)}", (entry_id,)).fetchone()
        unscoped_entry = row is not None and row[0] is None
    except (TypeError, ValueError):
        pass  # The payload validator owns malformed selectors.
    if not unscoped_entry and not payload.get("include_unattributed"):
        return None
    if not includes_unscoped(conn, request):
        return DispatchPermission(permission_key, None, None, error=permission_error_response(
            request, entry, "permission_denied", "feedback_unscoped_admin_required: only an org admin may review or archive notes without a project"))
    # Bulk writes still prove their named project's permission and bounded scope.
    return DispatchPermission(permission_key, None, None) if unscoped_entry else None
