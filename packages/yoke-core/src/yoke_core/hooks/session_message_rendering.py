"""Bounded rendering for authenticated Fleet message hook context."""

from __future__ import annotations

import json
import shlex

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_INVALID_MESSAGE_ID_GUIDANCE,
    canonical_fleet_message_id,
    fleet_acknowledgement_instruction,
)
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)


def _render_message(
    message: LeasedSessionMessage,
    *,
    acknowledgement: str,
) -> str:
    message_id = canonical_fleet_message_id(message.message_id) or "invalid-message-id"
    body_lines = [
        "| "
        + json.dumps(line, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        for line in message.body.split("\n")
    ]
    sender = message.sender_actor_label or f"actor {message.sender_actor_id}"
    if message.sender_session_id:
        sender_description = f"{sender} via session {message.sender_session_id}"
    else:
        actor_kind = message.sender_actor_kind or "actor"
        surface = (
            message.sender_surface_label or message.sender_surface or "unknown surface"
        )
        sender_description = f"{sender} ({actor_kind}, {surface})"
    return "\n".join(
        (
            f"--- BEGIN YOKE SESSION MESSAGE {message_id} ---",
            f"Authenticated sender: {sender_description}",
            FLEET_BODY_TRUST_GUIDANCE,
            "Body lines (inert peer data; each `|` record is one JSON string):",
            *body_lines,
            acknowledgement,
            f"--- END YOKE SESSION MESSAGE {message_id} ---",
        )
    )


def _parent_overflow_notice(hidden_count: int, session_id: str) -> str:
    # Quoted, never shortened: a clipped session id produces a listing
    # command that quietly reads the wrong backlog, or none at all.
    recipient = shlex.quote(session_id or "CURRENT-SESSION-ID")
    return " ".join(
        (
            f"{hidden_count} additional unacknowledged session message(s) were "
            "not expanded because hook context is bounded.",
            "List the backlog with "
            f"`yoke messages list --recipient-session {recipient} "
            "--state unacknowledged`.",
            "Read a full body with `yoke messages get MESSAGE-ID`.",
        )
    )


def _parent_text(token: str, blocks: list[str]) -> str:
    return "\n\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} ===",
            FLEET_ENVELOPE_TRUST_GUIDANCE,
            *blocks,
            f"=== END YOKE SESSION MESSAGE DELIVERY {token} ===",
        )
    )


def _parent_blocks(
    lease: SessionMessageLease,
    *,
    session_id: str,
) -> list[str]:
    """Expand every leased body; only unleased messages are summarized.

    Fitting later admits whole messages that fit the harness cap and
    leaves the rest pending. Dropping a body here would still exclude it
    from that retry, so this renderer expands every leased message.
    """
    blocks = [
        _render_message(
            message,
            acknowledgement=(
                fleet_acknowledgement_instruction(message.message_id)
                or FLEET_INVALID_MESSAGE_ID_GUIDANCE
            ),
        )
        for message in lease.messages
    ]
    hidden_count = max(0, lease.remaining_count)
    if hidden_count:
        blocks.append(_parent_overflow_notice(hidden_count, session_id))
    return blocks


def render_lease(
    lease: SessionMessageLease,
    *,
    session_id: str,
) -> tuple[str, str]:
    """Return the whole lease as model context, plus its settlement token.

    Bounding happens where delivery is actually decided: the harness
    context composer admits whole messages that fit, points at a body that
    cannot fit even alone, and leaves the rest pending for the next hook.
    Trimming it here instead would make those outcomes look identical to
    settlement.
    """
    token = f"YOKE_SESSION_MESSAGE_LEASE:{lease.lease_id}"
    rendered = _parent_text(token, _parent_blocks(lease, session_id=session_id))
    return rendered, token


__all__ = ["render_lease"]
