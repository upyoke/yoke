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
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)


MAX_FULL_MESSAGES_PER_INJECTION = 3
MAX_SESSION_MESSAGE_INJECTION_BYTES = 24 * 1024


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
    token: str,
    session_id: str,
) -> list[str]:
    total_count = len(lease.messages) + max(0, lease.remaining_count)
    selected: list[str] = []
    for message in lease.messages[:MAX_FULL_MESSAGES_PER_INJECTION]:
        proposed = [
            *selected,
            _render_message(
                message,
                acknowledgement=(
                    fleet_acknowledgement_instruction(message.message_id)
                    or FLEET_INVALID_MESSAGE_ID_GUIDANCE
                ),
            ),
        ]
        hidden_count = total_count - len(proposed)
        fixed_blocks = [*proposed]
        if hidden_count:
            fixed_blocks.append(_parent_overflow_notice(hidden_count, session_id))
        if len(_parent_text(token, fixed_blocks).encode("utf-8")) > (
            MAX_SESSION_MESSAGE_INJECTION_BYTES
        ):
            break
        selected = proposed
    hidden_count = total_count - len(selected)
    blocks = [*selected]
    if hidden_count:
        blocks.append(_parent_overflow_notice(hidden_count, session_id))
    return blocks


def render_lease(
    lease: SessionMessageLease,
    *,
    session_id: str,
) -> tuple[str, str]:
    """Return bounded model context and the durable settlement token."""
    token = f"YOKE_SESSION_MESSAGE_LEASE:{lease.lease_id}"
    rendered = _parent_text(
        token,
        _parent_blocks(lease, token=token, session_id=session_id),
    )
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
    """Render a bounded read-only view without granting receipt authority."""
    selected: list[str] = []
    for message in messages[:MAX_FULL_MESSAGES_PER_INJECTION]:
        proposed = [
            *selected,
            _render_message(message, acknowledgement=SUBAGENT_FLEET_GUIDANCE),
        ]
        hidden_count = len(messages) - len(proposed)
        fixed_blocks = [*proposed]
        if hidden_count:
            fixed_blocks.append(_child_overflow_notice(hidden_count))
        if len(_child_text(fixed_blocks).encode("utf-8")) > (
            MAX_SESSION_MESSAGE_INJECTION_BYTES
        ):
            break
        selected = proposed
    hidden_count = len(messages) - len(selected)
    if hidden_count:
        selected.append(_child_overflow_notice(hidden_count))
    return _child_text(selected)


__all__ = [
    "MAX_FULL_MESSAGES_PER_INJECTION",
    "MAX_SESSION_MESSAGE_INJECTION_BYTES",
    "render_child_view",
    "render_lease",
]
