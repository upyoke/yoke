"""Fleet message-body validation."""

from __future__ import annotations

from yoke_core.domain.session_message_types import SessionMessageError


__all__ = [
    "validate_body",
]


def validate_body(body: str, *, max_body_bytes: int) -> None:
    """Require a non-empty body within the configured byte limit."""
    body_bytes = len(body.encode("utf-8"))
    if body_bytes == 0:
        raise SessionMessageError("body_empty", "message body must not be empty")
    if body_bytes > max_body_bytes:
        raise SessionMessageError(
            "body_too_large",
            f"message body is {body_bytes} bytes; maximum is {max_body_bytes}",
            jsonpath="$.payload.body",
        )
