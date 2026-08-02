"""Refuse a session registration whose id the caller cannot corroborate.

``sessions begin`` is the one function that *creates* the identity every
later call is checked against, so it is the one place where an
unverifiable id does lasting damage: once the row exists, claims,
lifecycle transitions, and the board all treat it as a real session.

A legitimate caller always has the id in hand from its harness — the hook
reads it from the harness payload or env, and the bootstrap helper passes
that same value straight through — so ambient resolution reproduces it.
A caller that could *not* resolve ambient identity has nothing to register:
minting an id and declaring it produces a board row for a session that
never existed, and buries the infrastructure gap that caused the
resolution failure.

This check must run client-side. The declared id travels in the request
envelope, so by the time the server sees it there is nothing left to
compare against — only the calling process can observe its own
environment and process ancestry.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

from yoke_cli.config import machine_config
from yoke_contracts.session_identity import (
    AMBIENT_RESOLUTION_FAILED,
    ANCHORS_DIR_NAME,
    resolve_ambient_session_id,
)


UNCORROBORATED_SESSION_MESSAGE = (
    "session registration declared session id {declared!r}, which this "
    "process cannot corroborate. {ambient_note} A session id comes from "
    "the harness that owns the conversation — it is never minted by the "
    "caller, because a minted id registers a session that does not exist "
    "and hides the resolution failure behind a normal-looking row. "
    + AMBIENT_RESOLUTION_FAILED
)


def _ambient_note(ambient: Optional[str]) -> str:
    if ambient:
        return f"Ambient resolution for this process yielded {ambient!r}."
    return "Ambient resolution for this process yielded no session id."


def resolve_ambient(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Resolve this process's ambient session id, or ``None``.

    Mirrors the dispatcher's client-side resolver: env chain first, then
    the hook-written process-anchor ancestry registry. Never raises —
    a failed resolution is itself the signal this guard acts on.
    """
    try:
        anchors_dir = machine_config.yoke_home() / ANCHORS_DIR_NAME
        return resolve_ambient_session_id(
            anchors_dir, os.environ if env is None else env,
        )
    except Exception:  # noqa: BLE001 — an unresolvable ambient is the signal
        return None


def uncorroborated_reason(
    declared_session_id: Optional[str],
    *,
    env: Optional[Mapping[str, str]] = None,
    ambient_session_id: Optional[str] = None,
) -> Optional[str]:
    """Return a refusal message, or ``None`` when registration may proceed.

    ``None`` (proceed) covers the two legitimate shapes:

    * no declared id — the dispatcher stamps the ambient one, so there is
      nothing uncorroborated to check; and
    * a declared id equal to the ambient one — the caller is registering
      the session it is actually running under.

    ``ambient_session_id`` injects a resolved ambient for tests.
    """
    declared = (declared_session_id or "").strip()
    if not declared:
        return None
    ambient = (
        resolve_ambient(env)
        if ambient_session_id is None
        else ambient_session_id
    )
    if declared == (ambient or ""):
        return None
    return UNCORROBORATED_SESSION_MESSAGE.format(
        declared=declared, ambient_note=_ambient_note(ambient),
    )


__all__ = [
    "UNCORROBORATED_SESSION_MESSAGE",
    "resolve_ambient",
    "uncorroborated_reason",
]
