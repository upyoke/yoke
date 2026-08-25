"""Session and run namespaces for Yoke scratch paths.

Scratch lives under ``<project>/sessions/<session>/runs/<run>/`` so
concurrent sessions never collide and every transient file is
attributable. This module owns the two identity-bearing segments and the
path-safety check they share.

A run with no ambient session identity is namespaced
:data:`DEFAULT_SESSION_SEGMENT`, which is right for an operator running a
command from a plain terminal and wrong for anything a harness session
does. Watcher captures are the case where the difference bites: the
session-cwd guard admits a capture only when the session segment matches
the session making the call, so a capture minted under the placeholder is
written to a path the very next tool call is refused for — a denial that
names the path rather than the identity failure that produced it. So the
watcher-capture path asks for the segment through
:func:`require_resolved_session_segment`, which refuses up front, naming
the real cause and its recovery.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts.cursor_session_map import CURSOR_CONVERSATION_ENV_VAR
from yoke_contracts.session_identity import (
    ACTOR_ROLE_ENV_VAR,
    AMBIENT_RESOLUTION_FAILED,
)


DEFAULT_SESSION_SEGMENT = "session-unknown"
RUN_ENV_KEYS = ("YOKE_RUN_ID", "YOKE_EXECUTION_ID", "GITHUB_RUN_ID")

# Markers a harness stamps into every process it drives that do NOT carry
# an identity — the ones that do are already in the ambient chain, so
# their presence would have answered the identity question outright.
HARNESS_PRESENCE_ENV_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    CURSOR_CONVERSATION_ENV_VAR,
    ACTOR_ROLE_ENV_VAR,
)


class ScratchSessionIdentityError(RuntimeError):
    """A session-scoped scratch path was requested without an identity."""


def safe_segment(value: str) -> str:
    """Return ``value`` when it is usable as one path segment, else raise."""
    text = str(value).strip()
    if not text or text in {".", ".."}:
        raise ValueError("scratch path segment must be non-empty")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"unsafe scratch path segment: {value!r}")
    return text


def resolve_session_id() -> str:
    """Return the ambient session id, or ``""`` when none resolves."""
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or ""


def session_segment() -> str:
    """Return the session segment, falling back to the unknown placeholder."""
    return safe_segment(resolve_session_id() or DEFAULT_SESSION_SEGMENT)


def run_segment() -> str:
    """Return the run segment: a declared run id, else this process."""
    for key in RUN_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return safe_segment(value)
    return safe_segment(f"pid-{os.getpid()}")


def under_harness_session() -> bool:
    """Whether a harness is driving this process.

    Read from the harness's own markers rather than from the process
    tree, because the tree cannot answer it for the callers that need it
    most: a Claude background worker runs under pooled daemon processes
    whose command names carry a role suffix, so the ancestry walk finds
    no harness ancestor at all and would call a launched worker an
    operator terminal.
    """
    return any(os.environ.get(name, "").strip() for name in HARNESS_PRESENCE_ENV_VARS)


def require_resolved_session_segment() -> str:
    """Return the session segment, refusing the placeholder under a harness.

    An operator's own terminal is a legitimately session-less caller and
    keeps the placeholder. A harness session that reaches this point has
    an identity gap that would otherwise surface later as a path denial.
    """
    session_id = resolve_session_id()
    if session_id:
        return safe_segment(session_id)
    if under_harness_session():
        raise ScratchSessionIdentityError(
            "refusing to mint a session-scoped scratch path under "
            f"{DEFAULT_SESSION_SEGMENT!r} inside a harness session: "
            f"{AMBIENT_RESOLUTION_FAILED}"
        )
    return DEFAULT_SESSION_SEGMENT


__all__ = [
    "DEFAULT_SESSION_SEGMENT",
    "HARNESS_PRESENCE_ENV_VARS",
    "RUN_ENV_KEYS",
    "ScratchSessionIdentityError",
    "require_resolved_session_segment",
    "resolve_session_id",
    "run_segment",
    "safe_segment",
    "session_segment",
    "under_harness_session",
]
