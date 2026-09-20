"""What a recipient came for: the message body, and what was held back.

Kept beside the detail view rather than inside it because the routine read
of one message is two answers — the prose someone wrote, and an honest
account of the delivery evidence the read bounded. Neither belongs in the
summary table above them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, TextIO

from yoke_contracts.session_control.message_projection import (
    ATTEMPTS_WITHHELD_KEY,
    ATTEMPTS_WITHHELD_READ_KEY,
)


def write_body(message: Mapping[str, Any], stdout: TextIO) -> None:
    """Print the message body whole — it is what a recipient came for."""
    body = message.get("body")
    if not body:
        return
    print("BODY", file=stdout)
    print(str(body).rstrip("\n"), file=stdout)


def write_withheld_attempts(message: Mapping[str, Any], stdout: TextIO) -> None:
    """Name the attempt rows the routine read held back, and their read."""
    withheld = message.get(ATTEMPTS_WITHHELD_KEY)
    if not withheld:
        return
    read = message.get(ATTEMPTS_WITHHELD_READ_KEY)
    print(
        f"{withheld} earlier delivery attempt(s) not printed — {read}",
        file=stdout,
    )


def projected_message_writer(
    fields: Sequence[str],
) -> Callable[[Any, TextIO, TextIO], None]:
    """Print one value per requested field, in the order they were asked.

    A caller that named its fields wants those values, not a table framing
    them, so a projection prints the way ``yoke items get`` does.
    """

    def write(response: Any, stdout: TextIO, stderr: TextIO) -> None:
        del stderr
        if not response.success:
            return None
        message = (response.result or {}).get("message") or {}
        for field in fields:
            value = message.get(field)
            text = "" if value is None else str(value)
            stdout.write(text)
            if not text.endswith("\n"):
                stdout.write("\n")
        return None

    return write


__all__ = ["projected_message_writer", "write_body", "write_withheld_attempts"]
