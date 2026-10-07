"""Usage lines and ``--help`` text for the published-workflow-update commands."""

from __future__ import annotations


WORKFLOWS_CANON_STATUS_LIST_USAGE = (
    "yoke workflows canon-status list [--pending] [--session-id S] [--json]"
)
WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE = (
    "yoke workflows canon-update preview WORKFLOW [--session-id S] [--json]"
)
WORKFLOWS_CANON_UPDATE_APPLY_USAGE = (
    "yoke workflows canon-update apply WORKFLOW "
    "--expected-current-version N [--session-id S] [--json]"
)
WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE = (
    "yoke workflows canon-update apply-all WORKFLOW=VERSION "
    "[WORKFLOW=VERSION ...] [--session-id S] [--json]"
)
WORKFLOWS_CANON_FOLLOW_SET_USAGE = (
    "yoke workflows canon-follow set WORKFLOW (auto|manual) [--session-id S] [--json]"
)

_RECIPE = (
    "Recipe:\n"
    "  yoke workflows canon-status list --pending\n"
    "  yoke workflows canon-update preview WORKFLOW\n"
    "  yoke workflows canon-update apply WORKFLOW "
    "--expected-current-version CURRENT_VERSION\n"
)

CANON_STATUS_LIST_DESCRIPTION = (
    f"{WORKFLOWS_CANON_STATUS_LIST_USAGE}\n\n"
    "Lists every workflow that has a published canon: its selected version, "
    "its state (up_to_date, update_available, customized, "
    "customized_update_available), and whether new generations arrive by "
    "themselves (follow=auto) or wait for an operator (follow=manual). "
    "--pending narrows to workflows with an update waiting to be taken; "
    "each row's current_version is the value apply expects.\n\n" + _RECIPE
)
PREVIEW_DESCRIPTION = (
    f"{WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE}\n\n"
    "Shows the merge a take would publish, without publishing it: the paths "
    "taken from the newest generation, the local edits kept, and any "
    "conflicts. A conflicting update refuses to apply; resolve it by editing "
    "the workflow, then publish.\n\n" + _RECIPE
)
APPLY_DESCRIPTION = (
    f"{WORKFLOWS_CANON_UPDATE_APPLY_USAGE}\n\n"
    "Takes the newest published generation for one workflow, preserving local "
    "edits, and selects the result for newly created items. Existing item "
    "pins do not move. --expected-current-version is the selected version "
    "you previewed against (canon-status list prints it); a workflow that "
    "moved since refuses instead of being overwritten.\n\n" + _RECIPE
)
APPLY_ALL_DESCRIPTION = (
    f"{WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE}\n\n"
    "Takes several published updates in one action. Each WORKFLOW=VERSION "
    "names a workflow and the selected version it is expected to be on. Every "
    "entry is attempted and reported on its own: applied entries stay "
    "applied when another refuses. Exits non-zero when any entry refused.\n\n"
    "Recipe:\n"
    "  yoke workflows canon-status list --pending\n"
    "  yoke workflows canon-update apply-all issue=4 epic=7\n"
)
FOLLOW_DESCRIPTION = (
    f"{WORKFLOWS_CANON_FOLLOW_SET_USAGE}\n\n"
    "auto: the next boot takes each newly published generation by itself. "
    "manual: new generations wait for canon-update apply. Publishing a local "
    "edit or selecting an older version turns following off; this is the "
    "only way to turn it back on. Turning it on adopts nothing until the "
    "next boot or an explicit apply.\n\n" + _RECIPE
)


USAGE_BY_FUNCTION_ID = {
    "workflows.canon_status.list": WORKFLOWS_CANON_STATUS_LIST_USAGE,
    "workflows.canon_update.preview": WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE,
    "workflows.canon_update.apply": WORKFLOWS_CANON_UPDATE_APPLY_USAGE,
    "workflows.canon_update.apply_all": WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE,
    "workflows.canon_follow.set": WORKFLOWS_CANON_FOLLOW_SET_USAGE,
}

__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "APPLY_ALL_DESCRIPTION",
    "APPLY_DESCRIPTION",
    "CANON_STATUS_LIST_DESCRIPTION",
    "FOLLOW_DESCRIPTION",
    "PREVIEW_DESCRIPTION",
    "WORKFLOWS_CANON_FOLLOW_SET_USAGE",
    "WORKFLOWS_CANON_STATUS_LIST_USAGE",
    "WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE",
    "WORKFLOWS_CANON_UPDATE_APPLY_USAGE",
    "WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE",
]
