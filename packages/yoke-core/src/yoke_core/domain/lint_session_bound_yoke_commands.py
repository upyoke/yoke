"""Registered ``yoke`` subcommands whose authority is the calling session.

Most mutations are authorized by the actor behind the credential. A few are
not: a merge-candidate clearance, and relaxing the posture that requires
one, are answerable only by somebody who is not the worker waiting on the
merge. On one workstation every surface shares the operator's actor, so the
session is the only thing that separates them -- and the session id travels
in the envelope as the caller wrote it.

Passing another session's ``--session-id`` to one of these is therefore the
whole bypass, and it is stopped here, at the hook, before the command runs.
That is a mistake-stopper with an audit trail rather than a cryptographic
boundary: a caller determined to evade it still can, but not by accident and
not without doing something visibly deliberate.
"""

from __future__ import annotations

import re
from typing import Optional

#: ``(family, subcommand pattern)``. Matched around interleaved flags, so
#: ``yoke --env prod ...`` and ``yoke dev run -- yoke ...`` both match and a
#: wrapper cannot launder the command.
SESSION_BOUND_YOKE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("yoke/decision-requests-resolve", r"\bdecision-requests\s+resolve\b"),
    (
        "yoke/workflows-item-posture-amend",
        r"\bworkflows\s+item-posture\s+amend\b",
    ),
)

#: The posture key whose relaxation carries the same authority as clearing a
#: candidate. Selecting it is always allowed; only removing it is bound.
GUARDED_POSTURE_KEY = "merge_candidate_review"

_YOKE_RE = re.compile(r"\byoke\b")
_COMMAND_RES = tuple(
    (family, re.compile(pattern)) for family, pattern in SESSION_BOUND_YOKE_COMMANDS
)
_POSTURE_RELAX_RE = re.compile(r"--clear\b|--value[=\s]+(?!true\b)")


def session_bound_yoke_family(command: str) -> Optional[str]:
    """Name the session-bound ``yoke`` subcommand ``command`` invokes."""
    if not _YOKE_RE.search(command):
        return None
    for family, regex in _COMMAND_RES:
        if not regex.search(command):
            continue
        if family.endswith("item-posture-amend"):
            if GUARDED_POSTURE_KEY not in command:
                return None
            if not _POSTURE_RELAX_RE.search(command):
                return None
        return family
    return None


__all__ = [
    "GUARDED_POSTURE_KEY",
    "SESSION_BOUND_YOKE_COMMANDS",
    "session_bound_yoke_family",
]
