"""Bounded rendering for authenticated Fleet message hook context."""

from __future__ import annotations

import json
import shlex

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_INVALID_MESSAGE_ID_GUIDANCE,
    SUBAGENT_FLEET_GUIDANCE,
    canonical_fleet_message_id,
    fleet_acknowledgement_instruction,
)
from yoke_contracts.hook_inline_context import ENVELOPE_INLINE_CONTEXT_BYTES
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
            "Read a full body with `yoke messages get MESSAGE-ID --json`.",
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

    The lease is one settlement unit: whatever it holds is marked injected
    together. Dropping a body here therefore issues a receipt for text this
    block never carried, and the omitted message is excluded from the
    pending-only retry that would have carried it next.
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
    context composer either carries this block intact or replaces it with
    the overflow pointer that names every message and keeps each receipt
    pending. Trimming it here instead would make both outcomes look
    identical to settlement.
    """
    token = f"YOKE_SESSION_MESSAGE_LEASE:{lease.lease_id}"
    rendered = _parent_text(token, _parent_blocks(lease, session_id=session_id))
    return rendered, token


def _child_text(blocks: list[str]) -> str:
    return "\n\n".join(
        (
            "=== BEGIN YOKE SESSION MESSAGE READ-ONLY CHILD VIEW ===",
            "These messages address the registered parent session and are visible "
            "here because this child shares that session.",
            *blocks,
            "=== END YOKE SESSION MESSAGE READ-ONLY CHILD VIEW ===",
        )
    )


def _child_overflow_notice(hidden_count: int) -> str:
    return (
        f"{hidden_count} additional parent message(s) were not expanded because "
        "hook context is bounded. Notify the parent through the harness-native "
        "parent/subagent channel."
    )


def render_child_view(messages: tuple[LeasedSessionMessage, ...]) -> str:
    """Render a bounded read-only view without granting receipt authority.

    This block settles no receipt, so summarizing part of it falsifies
    nothing. It bounds itself because the composer classifies it as a hint
    and drops an oversized hint whole rather than pointing at it, and the
    smallest harness inline ceiling is what it has to survive.
    """
    selected: list[str] = []
    for message in messages:
        proposed = [
            *selected,
            _render_message(message, acknowledgement=SUBAGENT_FLEET_GUIDANCE),
        ]
        hidden_count = len(messages) - len(proposed)
        fixed_blocks = [*proposed]
        if hidden_count:
            fixed_blocks.append(_child_overflow_notice(hidden_count))
        if len(_child_text(fixed_blocks).encode("utf-8")) > (
            ENVELOPE_INLINE_CONTEXT_BYTES
        ):
            break
        selected = proposed
    hidden_count = len(messages) - len(selected)
    if hidden_count:
        selected.append(_child_overflow_notice(hidden_count))
    return _child_text(selected)


__all__ = [
    "render_child_view",
    "render_lease",
]
