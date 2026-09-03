"""Why a harness refused a Yoke command, and the one line that repairs it.

A harness that has not been given the unattended posture reports a blocked
control-plane call as ``Operation not permitted`` somewhere inside a
connection error. That names the syscall, not the boundary, so the failure
reads as a broken database rather than a config nobody has written yet.

Naming the *wrong* harness would be worse than naming none, so identification
is deliberately conservative and returns nothing when the evidence is
ambiguous.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_contracts.harness_unattended_posture import (
    CODEX_FAMILY,
    CURSOR_FAMILY,
    POSTURE_RECOVERY,
)

#: Harnesses that run commands inside an OS sandbox, where a refused socket
#: or write is the sandbox and not the system. Claude is deliberately absent:
#: its gate is an approval prompt, so its commands run unsandboxed either way.
OS_SANDBOXING_HARNESSES: Tuple[str, ...] = (CODEX_FAMILY, CURSOR_FAMILY)


def running_harness_family() -> Optional[str]:
    """Family of the harness running this process, or ``None``.

    The process walk answers first and is the trustworthy channel, but it
    reads the process table — which is one of the things a sandbox denies,
    exactly when this question is being asked. So the session env vars are
    the fallback, and only when a single family's vars are present: every
    harness exports its own into whatever it starts, so a harness opened
    from inside another one's shell carries both, and picking either would
    name the launcher as often as the launcher's child. Ambiguous evidence
    yields ``None`` — a missing hint costs nothing, while a hint naming the
    wrong harness sends someone to repair a config that was never involved.
    """
    from yoke_contracts.harness_family_identity import (
        family_env_session_id,
        nearest_harness_family,
    )

    try:
        family = nearest_harness_family()
        if family:
            return family
        stamped = [
            candidate
            for candidate in CANONICAL_HARNESS_IDS
            if family_env_session_id(candidate)
        ]
        return stamped[0] if len(stamped) == 1 else None
    except Exception:  # noqa: BLE001 — identity must never raise here
        return None


def sandbox_recovery(harness_id: Optional[str] = None) -> Optional[str]:
    """Recovery for a command a harness *sandbox* refused, or ``None``.

    Narrower than the posture as a whole: Claude's prompting is an approval
    gate, not an OS sandbox, so a refused socket in a Claude session is an
    ordinary system problem and saying otherwise would send someone to
    repair a setting that was never involved. ``None`` therefore covers
    "not under a harness", "under Claude", and "under one Yoke does not
    manage" alike, so a caller can append this without first having to know
    which harness it is.
    """
    if harness_id is None:
        harness_id = running_harness_family()
    if str(harness_id or "").strip() not in OS_SANDBOXING_HARNESSES:
        return None
    return (
        f"A {harness_id} session runs commands under its own approval and "
        f"sandbox policy, which blocks Yoke's control plane until the "
        f"unattended posture is written. {POSTURE_RECOVERY}"
    )


__all__ = [
    "OS_SANDBOXING_HARNESSES",
    "running_harness_family",
    "sandbox_recovery",
]
