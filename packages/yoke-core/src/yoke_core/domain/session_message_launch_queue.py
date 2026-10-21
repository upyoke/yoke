"""Item mail waiting for the exact worker already being launched."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.project_identity import placeholder, render_item_ref
from yoke_core.domain.session_launch_assignment import assignment_name_prefix
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.session_message_anchors import _resolve_item_ref
from yoke_core.domain.session_message_recipient_rows import insert_session_receipt
from yoke_core.domain.session_message_types import SessionMessageError, utc_now
from yoke_core.domain.session_message_zero_recipients import zero_recipients_detail
from yoke_core.domain.work_claim_holder import holder_session_for_item
from yoke_core.domain.work_claim_target_sql import scope_text_sql


def resolve_item_launch_mail(conn, selector, recipients, *, now):
    """An unheld, directly addressed item may wait for its steering launch."""
    if recipients or len(selector.public_refs) != 1:
        return recipients, None
    ref = selector.public_refs[0]
    item_id, project_id = _resolve_item_ref(conn, ref)
    from yoke_core.domain.session_message_selectors import resolve_recipients

    if holder_session_for_item(conn, item_id).get("holder_session_id"):
        return resolve_recipients(conn, selector, now=now), None
    p = placeholder(conn)
    canonical_ref = render_item_ref(conn, item_id, required=True)
    row = conn.execute(
        "SELECT launch_id,state,deadline_at FROM session_launches "
        f"WHERE project_id={p} AND session_name LIKE {p} AND origin='steering' "
        "ORDER BY created_at DESC,launch_id DESC LIMIT 1",
        (project_id, f"{assignment_name_prefix(canonical_ref)} %"),
    ).fetchone()
    if row is None:
        return recipients, None
    launch_id, state, deadline = row
    if state == "succeeded":
        fresh = resolve_recipients(conn, selector, now=now)
        if fresh:
            return fresh, None
    direct = not any(
        value for key, value in selector.model_dump().items() if key != "public_refs"
    )
    eligible = state in IN_FLIGHT_LAUNCH_STATES and (
        state in {"queued", "assigned"} or parse_instant(deadline) > now
    )
    if not eligible or not direct:
        raise SessionMessageError(
            "zero_recipients",
            f"{zero_recipients_detail(selector)} Launch {launch_id} is {state}; "
            "only a direct item address can queue for an in-flight launch. "
            f"Inspect `yoke session-control launch get {launch_id}`; "
            f"retry `yoke say --item {canonical_ref} --stdin` after staffing.",
        )
    return recipients, {"launch_id": str(launch_id), "project_id": project_id}


def launch_confirmation(token, launch):
    if launch is None:
        return token
    return hashlib.sha256(f"{token}:{launch['launch_id']}".encode()).hexdigest()


def launch_snapshot(snapshot, launch):
    if launch is None:
        return snapshot
    return {**snapshot, "anchor": "launch", **launch}


def message_intent_json(snapshot):
    """A resolved launch address does not change the sender's item intent."""
    if snapshot.get("anchor") == "launch" and snapshot.get("public_refs"):
        snapshot = {
            key: value
            for key, value in snapshot.items()
            if key not in {"anchor", "launch_id", "project_id"}
        }
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def launch_recipient(conn, details: dict[str, Any], *, now=None, launch_row=None):
    """Project waiting and failed delivery from existing message/launch facts."""
    snapshot = details.get("selector_snapshot") or {}
    if (
        snapshot.get("anchor") != "launch"
        or not snapshot.get("public_refs")
        or details.get("recipients")
    ):
        return None
    launch_id = snapshot["launch_id"]
    row = (
        launch_row
        or conn.execute(
            "SELECT state,registered_session_id,deadline_at FROM session_launches "
            f"WHERE launch_id={placeholder(conn)}",
            (launch_id,),
        ).fetchone()
    )
    current = utc_now() if now is None else now
    state = "pending"
    reason = "awaiting_work_claim"
    if details.get("cancelled_at"):
        state, reason = "cancelled", "message_cancelled"
    elif details.get("expires_at") and parse_instant(details["expires_at"]) <= current:
        state, reason = "expired", "message_expired"
    elif row is None or row[0] not in {*IN_FLIGHT_LAUNCH_STATES, "succeeded"}:
        state, reason = "cancelled", f"launch_{row[0] if row else 'missing'}"
        if row is not None and row[0] == "expired":
            state = "expired"
    elif (
        row[0] not in {"queued", "assigned", "succeeded"}
        and parse_instant(row[2]) <= current
    ):
        state, reason = "expired", "launch_deadline_elapsed"
    return {
        **{key: snapshot[key] for key in ("launch_id", "project_id")},
        "label": f"launch {launch_id}",
        "state": state,
        "reason": reason,
        "summary": f"{reason}: launch {launch_id}; inspect `yoke session-control "
        f"launch get {launch_id}`. Cancel this message before resending to another worker.",
    }


def launch_result(conn, details, *, now=None):
    recipient = launch_recipient(conn, details, now=now)
    return {"launch_recipient": recipient} if recipient else {}


def queued_launch_sql(marker):
    """The stored launch address, using each database's existing JSON support."""
    if marker == "%s":
        return "(CASE WHEN m.selector_snapshot::jsonb ? 'public_refs' THEN m.selector_snapshot::jsonb ->> 'launch_id' END)"
    return "(CASE WHEN json_type(m.selector_snapshot,'$.public_refs') IS NOT NULL THEN json_extract(m.selector_snapshot,'$.launch_id') END)"


def queued_message_clause(marker, *, state=None, now=None):
    """Match undelivered launch mail without inventing a recipient row."""
    link = queued_launch_sql(marker)
    open_launch = (
        "l.state IN ('queued','assigned','succeeded') OR "
        f"(l.state IN ('launching','awaiting_registration') AND l.deadline_at>{marker})"
    )
    open_message = f"m.cancelled_at IS NULL AND m.expires_at>{marker}"
    params = []
    condition = "1=1"
    if state in {"pending", "unacknowledged"}:
        condition = f"{open_message} AND ({open_launch})"
        params = [now, now]
    elif state == "expired":
        condition = (
            f"m.cancelled_at IS NULL AND (m.expires_at<={marker} "
            "OR l.state='expired' OR (l.state IN ('launching','awaiting_registration') "
            f"AND l.deadline_at<={marker}))"
        )
        params = [now, now]
    elif state == "cancelled":
        condition = (
            f"m.cancelled_at IS NOT NULL OR (m.expires_at>{marker} "
            "AND l.state IN ('failed','cancelled','outcome_unknown'))"
        )
        params = [now]
    elif state is not None:
        condition = "1=0"
    return (
        "(NOT EXISTS (SELECT 1 FROM session_message_recipients qr "
        "WHERE qr.message_id=m.message_id) AND EXISTS "
        f"(SELECT 1 FROM session_launches l WHERE l.launch_id={link} "
        f"AND ({condition})))",
        params,
    )


def bind_item_launch_mail(conn, *, session_id, now):
    """Give the claiming session its queued mail before its next hook lease."""
    from yoke_core.domain.session_message_selectors import resolve_recipients

    p = placeholder(conn)
    launch_id = scope_text_sql(conn, "m.selector_snapshot", "launch_id")
    from yoke_core.domain import db_backend

    lock = (
        " FOR UPDATE OF m SKIP LOCKED"
        if db_backend.connection_is_postgres(conn)
        else ""
    )
    rows = conn.execute(
        "SELECT m.message_id,m.selector_snapshot,m.created_at,m.sender_actor_id "
        "FROM session_messages m JOIN session_launches l "
        f"ON l.launch_id={launch_id} WHERE l.registered_session_id={p} "
        f"AND m.cancelled_at IS NULL AND m.expires_at>{p} "
        "AND l.state IN ('awaiting_registration','succeeded') "
        f"AND (l.state='succeeded' OR l.deadline_at>{p}) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_recipients r "
        "WHERE r.message_id=m.message_id)" + lock,
        (session_id, instant_parameter(conn, now), instant_parameter(conn, now)),
    ).fetchall()
    for message_id, raw, created_at, actor_id in rows:
        snapshot = json.loads(raw)
        if snapshot.get("anchor") != "launch" or not snapshot.get("public_refs"):
            continue
        selector = RecipientSelector(public_refs=snapshot["public_refs"])
        recipients = resolve_recipients(conn, selector, actor_id=actor_id, now=now)
        for recipient in recipients:
            if recipient.session_id == session_id:
                insert_session_receipt(
                    conn,
                    message_id=message_id,
                    recipient=recipient,
                    created_at=parse_instant(created_at),
                    wake_after=now,
                )
