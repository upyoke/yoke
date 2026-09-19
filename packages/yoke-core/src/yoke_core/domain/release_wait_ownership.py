"""Who owns an item that has merged and is still waiting on its delivery.

A Dash whose merge lands at the pinned release wait is not finished. Its
delivery still has to run, its post-deploy validation still has to be
walked, and only then does the item reach done. The session that merged it
is the one carrying that context, so it keeps the item's work claim and
waits rather than reporting and ending.

Keeping the claim was already what the close-out transition did, and it was
the only path that agreed. The launched-worker mandate told every session to
END after its DONE report, the Dash close-out offered a claim release beside
it, and the stale sweep reclaimed whatever went quiet -- so one retained
claim was undone by three separate paths, and an item at its release wait
was left unowned more often than it was held. This module is the single
place that says what a release-wait owner is and what may happen to it; the
mandate, the merge close-out, and the sweep all read it from here rather
than each carrying its own idea.

This module owns the concept alone: what a release-wait owner is, and the
words a worker is taught about being one. Its two collaborators own the
writes, because each has a transport this one must not assume:

* :mod:`release_wait_park` stamps the park from the merge close-out, which
  is installed-client code and relays rather than connecting;
* :mod:`release_wait_sweep` decides what the stale sweep may do to a quiet
  owner, and hands an abandoned item to the project's steering seat.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_target_sql import scope_int_sql
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

TOUCH_FUNCTION = "sessions.touch"
HOLDER_FUNCTION = "claims.work.holder_get"


RELEASE_WAIT_RETENTION_TEACHING = (
    "A merge that lands your item at its pinned release wait is a completed "
    "merge that is NOT a finished item: the delivery still has to run and "
    "its post-deploy validation still has to be walked before the item "
    "reaches done. That close-out therefore keeps your work claim and parks "
    "your session with the wait named, and you keep both. Do NOT release the "
    "claim and do NOT end your session there — report what landed in your "
    "own output, say you are waiting on delivery, and stop deliberately. The "
    "deployment wake re-enters you when your delivery clears or its QA stage "
    "needs you. A stage that wants your evidence is run by naming that stage "
    "AND your item, because a stage credits only requirements bound to its "
    "own name: `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE "
    "--member <ITEM> --project P` (that wrapper, not "
    "`yoke watch qa-case`, which wraps the narrower requirement-id form). "
    "Add `--plan PLAN` only when the wake says the stage names no cases: a "
    "stage that already names its own refuses --plan, because a plan there "
    "materializes a second, duplicate set of obligations beside the ones it "
    "credits. The wake prints the exact recipe for its own stage. "
    "The run-wide form and "
    "`yoke qa case run` do not credit it. Then re-run the same "
    "`yoke merge item` command with --result and "
    "--verification, and it finishes the close-out. Only once the item "
    "reaches done do you send the DONE report and end. Any prompt that wakes "
    "you CLEARS that park, including one that turns out not to finish the "
    "item, so whenever you go quiet still short of done — a wake you handled, "
    "a close-out that refused, a message about something else — re-park "
    "before stopping: `yoke sessions touch --mode parked --reason \"awaiting "
    "<ITEM> delivery\"`. A release-wait owner that goes quiet without that "
    "park is treated as gone and its item is handed to steering, so the park "
    "is what keeps the item yours."
)


def park_reason(public_ref: str) -> str:
    """The concrete deployment wait a parked release-wait owner declares."""
    named = (public_ref or "").strip() or "this item"
    return (
        f"awaiting {named} delivery: deployment run, then post-deploy "
        f"validation and the done close-out"
    )


def item_at_release_wait(row: Any, status: str) -> bool:
    """Whether a joined item/workflow-version row stands at its pinned wait.

    An unreadable pin answers no. A definition this cannot interpret is not
    evidence that an item is waiting, and every caller here treats "waiting"
    as a reason to hold something open or to announce something — both worse
    to get wrong than a missed spare.
    """
    try:
        release_stage = delivery_redirect_stage(workflow_runtime_from_row(row))
    except Exception:  # noqa: BLE001 - an unreadable pin names no wait
        return False
    return release_stage is not None and str(status or "") == release_stage


def owned_release_waits(conn: Any, session_id: str) -> list[dict[str, Any]]:
    """Items at their pinned release wait whose claim ``session_id`` holds.

    An unreadable pin answers "not a release wait" for that item alone: a
    definition this call cannot interpret is not evidence that the sweep
    should spare a session, and treating it as one would let a corrupt row
    pin a claim open forever.
    """
    required = ("work_claims", "items", "projects", "workflow_versions")
    if not session_id or not all(_table_exists(conn, name) for name in required):
        return []
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    rows = conn.execute(
        f"SELECT i.id AS item_id,i.project_id,i.status,i.project_sequence,"
        "i.workflow_id,i.workflow_version_id,p.public_item_prefix,"
        "v.version,v.definition_json,v.definition_digest "
        "FROM work_claims wc "
        f"JOIN items i ON i.id={item_id} "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN workflow_versions v ON v.id=i.workflow_version_id "
        "WHERE wc.released_at IS NULL AND wc.target_kind='item' "
        "AND wc.session_id=%s ORDER BY i.id",
        (session_id,),
    ).fetchall()
    owned: list[dict[str, Any]] = []
    for row in rows:
        status = str(row["status"] or "")
        if not item_at_release_wait(row, status):
            continue
        owned.append(
            {
                "item_id": int(row["item_id"]),
                "project_id": int(row["project_id"]),
                "public_ref": format_item_ref(
                    None, row["public_item_prefix"], row["project_sequence"]
                ),
                "status": status,
            }
        )
    return owned


__all__ = [
    "HOLDER_FUNCTION",
    "RELEASE_WAIT_RETENTION_TEACHING",
    "TOUCH_FUNCTION",
    "item_at_release_wait",
    "owned_release_waits",
    "park_reason",
]
