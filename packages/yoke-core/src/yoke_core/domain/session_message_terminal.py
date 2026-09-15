"""Resolve the item and leg a terminal DONE report names, and refuse guesses."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.terminal_report import parse_terminal_report
from yoke_core.domain import db_backend
from yoke_core.domain.item_ref_resolution import internal_ids_for_refs
from yoke_core.domain.session_item_scope import (
    SessionItemScope,
    session_claim_for_item,
)
from yoke_core.domain.session_message_types import SessionMessageError


ITEM_UNSPECIFIED = "terminal_report_item_unspecified"
ITEM_UNKNOWN = "terminal_report_item_unknown"
ITEM_UNRELATED = "terminal_report_item_unrelated"
_HEADING_REPAIR = (
    "Rewrite the first line as `DONE PREFIX-N <one-line summary>` naming "
    "the item this session holds or has released; do not omit the ref or "
    "mention it only later in the body."
)


def resolve_terminal_report_item(
    conn: Any,
    *,
    sender_session_id: str | None,
    body: str,
) -> SessionItemScope | None:
    """The named item for a DONE report, or ``None`` when the body is not one.

    A DONE report that cannot name a claim this sender actually holds or
    released is refused with a repairable code; it never falls back to a
    different live claim.
    """
    parsed = parse_terminal_report(body)
    if parsed is None:
        return None
    if not sender_session_id:
        raise SessionMessageError(
            ITEM_UNSPECIFIED,
            "A DONE report must be sent from the session that holds or "
            f"released the named item. {_HEADING_REPAIR}",
            jsonpath="$.payload.body",
        )
    if parsed.item_ref is None:
        raise SessionMessageError(
            ITEM_UNSPECIFIED,
            f"A DONE report did not name PREFIX-N in the heading. {_HEADING_REPAIR}",
            jsonpath="$.payload.body",
        )
    item_id = internal_ids_for_refs(conn, [parsed.item_ref]).get(parsed.item_ref)
    if item_id is None:
        raise SessionMessageError(
            ITEM_UNKNOWN,
            f"`DONE {parsed.item_ref}` names no item. {_HEADING_REPAIR}",
            jsonpath="$.payload.body",
        )
    claimed = session_claim_for_item(conn, sender_session_id, item_id)
    if claimed is None:
        raise SessionMessageError(
            ITEM_UNRELATED,
            f"`DONE {parsed.item_ref}` is not work this session holds or has "
            "released. Report the item you actually worked, or acquire that "
            "item's claim first.",
            jsonpath="$.payload.body",
        )
    return claimed


def acknowledged_authorization(conn: Any, session_id: str | None) -> str | None:
    """The last instruction this session acknowledged, or ``None`` for no work.

    A resumed worker acknowledges the message authorizing its next leg before
    doing that work, whether or not the resume also hands it a fresh claim. So
    a worker still holding an unfinished lane — kept for delivery or a retest —
    reports that completion under a moved authorization rather than having to
    release the claim to be heard.
    """
    if not session_id:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT message_id FROM session_message_recipients "
        f"WHERE session_id = {marker} AND state = 'acknowledged' "
        "ORDER BY acknowledged_at DESC, message_id DESC LIMIT 1",
        (str(session_id),),
    ).fetchone()
    return None if row is None else str(dict(row)["message_id"])


__all__ = [
    "ITEM_UNKNOWN",
    "ITEM_UNRELATED",
    "ITEM_UNSPECIFIED",
    "acknowledged_authorization",
    "resolve_terminal_report_item",
]
