"""Scope-specific recovery for a corrected case that still owns its key."""

from shlex import quote

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import render_item_ref, resolve_project_slug


def corrected_case_recovery(conn, failed):
    """Refresh member snapshots before retrying their corrected plan content."""
    member = failed.get("deployment_member_item_id")
    if member:
        item = query_one(conn, "SELECT project_id FROM items WHERE id=%s", (member,))
        project = resolve_project_slug(conn, int(item["project_id"]))
        ref = render_item_ref(conn, int(member))
        scope = (
            f"--item {quote(ref)} --stage {quote(str(failed['deployment_stage']))} "
            f"--plan {quote(str(failed['plan_id']))} --project {quote(project)}"
        )
        return (
            "Refresh the member's stored case, then retry without --replaces: "
            f"`yoke qa plan rematerialize {scope}` followed by "
            f"`yoke qa plan run {scope}`."
        )
    return (
        "To test corrected code, retry that requirement with `yoke qa plan run` "
        "(its stage scope, no --replaces): a fresh attempt runs against the deployed release."
    )
