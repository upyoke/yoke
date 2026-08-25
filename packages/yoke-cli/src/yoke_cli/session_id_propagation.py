"""Carry an explicit ``--session-id`` across one invocation's whole call tree.

``--session-id`` is the operator-debug override for ambient identity, and
argparse hands it to exactly one adapter. That was enough while every
command did its own work, but a command that delegates — ``yoke merge
item`` landing a branch and then recording its evidence, a runner
spawning a child ``yoke`` — resolves identity again further down, where
the flag never reached. The observed failure is the worst shape
available: the outward half succeeded and the recording half refused
with ``actor_session_missing``, leaving a merged item with no evidence.

Stamping the override into the environment for the duration of the
invocation puts it at the head of the canonical ambient chain
(:data:`yoke_contracts.session_identity.AMBIENT_ENV_VARS`), so in-process
re-resolution and spawned children alike see the identity the operator
named. The flag stays in ``argv``: adapters that parse it keep working,
and this only fills the gap for the ones that never saw it.

Scanning stops at a bare ``--`` because everything after it belongs to a
wrapped command (``yoke watch pytest -- ...``), whose flags are not ours
to interpret.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator, Optional, Sequence

from yoke_contracts.session_identity import AMBIENT_ENV_VARS


SESSION_ID_FLAG = "--session-id"

# The head of the ambient chain, so a stamped override outranks whatever
# the harness itself exported for this process.
SESSION_ID_ENV_VAR = AMBIENT_ENV_VARS[0]


def explicit_session_id(argv: Sequence[str]) -> Optional[str]:
    """Return the ``--session-id`` value in ``argv``, or ``None``.

    Accepts both spellings argparse does (``--session-id X`` and
    ``--session-id=X``). A flag with a missing, empty, or flag-shaped
    value yields ``None`` — argparse owns reporting that as a usage
    error, and guessing here would stamp a nonsense identity.
    """
    for index, token in enumerate(argv):
        if token == "--":
            return None
        if token == SESSION_ID_FLAG:
            following = argv[index + 1] if index + 1 < len(argv) else ""
            value = following.strip()
            return value if value and not value.startswith("-") else None
        if token.startswith(SESSION_ID_FLAG + "="):
            value = token.partition("=")[2].strip()
            return value or None
    return None


@contextlib.contextmanager
def propagated_session_identity(argv: Sequence[str]) -> Iterator[Optional[str]]:
    """Stamp any explicit ``--session-id`` for the body, then restore.

    Yields the propagated id, or ``None`` when ``argv`` carries no
    override and the environment is left untouched — ambient resolution
    is already correct for every descendant in that case.
    """
    session_id = explicit_session_id(argv)
    if session_id is None:
        yield None
        return
    previous = os.environ.get(SESSION_ID_ENV_VAR)
    os.environ[SESSION_ID_ENV_VAR] = session_id
    try:
        yield session_id
    finally:
        if previous is None:
            os.environ.pop(SESSION_ID_ENV_VAR, None)
        else:
            os.environ[SESSION_ID_ENV_VAR] = previous


__all__ = [
    "SESSION_ID_ENV_VAR",
    "SESSION_ID_FLAG",
    "explicit_session_id",
    "propagated_session_identity",
]
