"""Shared ``--body-file | --stdin`` content-input helper.

Hosts the parsing pattern that both
:mod:`yoke_core.domain.item_field_transform` and
:mod:`yoke_core.api.service_client_backlog_update` use to resolve the
content for a structured-field write. Centralises the canonical error
strings (``cannot use both --stdin and --body-file; pick one``,
``content input missing (--stdin or --body-file required)``) and the
file-not-found surface so callers can not drift apart.

The two consumers have slightly different needs:

- ``item_field_transform`` always works with resolved text content (the
  additive transforms operate on strings in memory).
- ``service_client_backlog_update`` keeps passing ``file_path`` to
  :func:`yoke_core.domain.backlog.execute_structured_write` for the
  body-file branch so existing tests that assert the file-path round-trip
  remain meaningful.

The helper supports both shapes by returning a small
:class:`ContentInput` record with ``mode``, ``content``, and
``file_path``. Stdin callers always read content immediately; body-file
callers receive the path and read it themselves through
:func:`read_body_file_or_raise` (which provides a clean
file-not-found surface) when they want resolved content.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional


MUTUAL_EXCLUSION_ERROR = "cannot use both --stdin and --body-file; pick one"
MISSING_INPUT_ERROR = "content input missing (--stdin or --body-file required)"


class ContentInputError(Exception):
    """Structured error from content-input parsing.

    ``message`` is the operator-facing string (already in the canonical
    form). ``exit_code`` lets callers preserve historical exit-code
    semantics (mutual exclusion = 2, anything else = 1).
    """

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True)
class ContentInput:
    """Resolved content-input descriptor for one CLI invocation."""

    mode: str  # "stdin" or "body-file"
    content: Optional[str] = None
    file_path: Optional[str] = None


def resolve_content_input(
    *, stdin_flag: bool, body_file: Optional[str],
) -> ContentInput:
    """Validate ``--stdin`` / ``--body-file`` flags and resolve content.

    For stdin mode, reads from :data:`sys.stdin` immediately and stores
    the result on the returned record. For body-file mode, returns the
    path; callers decide whether to read it via
    :func:`read_body_file_or_raise` or pass the path through to a
    downstream surface.

    Raises :class:`ContentInputError` for the canonical mutual-exclusion
    and missing-input cases. The mutual-exclusion error uses
    ``exit_code=2`` to match the existing
    ``service_client_backlog_update`` shape.
    """
    if stdin_flag and body_file:
        raise ContentInputError(MUTUAL_EXCLUSION_ERROR, exit_code=2)
    if not stdin_flag and not body_file:
        raise ContentInputError(MISSING_INPUT_ERROR, exit_code=1)
    if body_file:
        return ContentInput(mode="body-file", file_path=body_file)
    return ContentInput(mode="stdin", content=sys.stdin.read())


def read_body_file_or_raise(path: str) -> str:
    """Read ``--body-file`` contents with a clean error surface.

    Raises :class:`ContentInputError` (exit code 1) for missing or
    unreadable paths. The message names the path so the operator does
    not have to guess which argument was wrong.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        raise ContentInputError(
            f"--body-file path not found: {path}", exit_code=1,
        ) from None
    except OSError as exc:
        raise ContentInputError(
            f"--body-file read failed: {path}: {exc}", exit_code=1,
        ) from None


__all__ = [
    "ContentInput",
    "ContentInputError",
    "MISSING_INPUT_ERROR",
    "MUTUAL_EXCLUSION_ERROR",
    "read_body_file_or_raise",
    "resolve_content_input",
]
