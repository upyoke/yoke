"""Identify the ambient harness even when its sandbox denies the process table."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS


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


__all__ = ["running_harness_family"]
