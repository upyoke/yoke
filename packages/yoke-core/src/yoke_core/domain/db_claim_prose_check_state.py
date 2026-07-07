"""Claim-state readers for the prose-vs-claim gate.

Owns the JSON-tolerant readers over the stored ``db_mutation_profile``,
including the operator-reviewed negative-claim attestation the
``db_claim.amend`` workflow stamps onto ``state="none"`` profiles:

* :func:`_claim_state` — parse-and-extract the ``state`` field from a
  stored profile JSON value.
* :func:`_claim_is_declared` / :func:`_claim_is_none` — boolean wrappers
  used by :func:`yoke_core.domain.db_claim_prose_check.check`.
* :func:`_claim_reviewed_negative` — reads the ``reviewed_negative``
  attestation off the stored profile JSON. The attestation is state on
  the item row; the ``DbClaimAmended`` events ledger is telemetry/audit
  only and is not consulted.

The detection vocabulary lives in
:mod:`yoke_core.domain.db_claim_prose_check_triggers`; the public
composition surface lives in
:mod:`yoke_core.domain.db_claim_prose_check`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from yoke_core.domain.db_mutation_profile import is_reviewed_negative


def _parse_profile(profile_raw: Any) -> Optional[Dict[str, Any]]:
    if not profile_raw:
        return None
    if isinstance(profile_raw, dict):
        return profile_raw
    if isinstance(profile_raw, str):
        try:
            parsed = json.loads(profile_raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _claim_state(profile_raw: Any) -> Optional[str]:
    parsed = _parse_profile(profile_raw)
    if parsed is None:
        return None
    state = parsed.get("state")
    return state if isinstance(state, str) else None


def _claim_is_declared(profile_raw: Any) -> bool:
    """True when the parsed profile JSON declares a governed DB mutation."""
    return _claim_state(profile_raw) == "declared"


def _claim_is_none(profile_raw: Any) -> bool:
    """True when the parsed profile JSON is explicitly the negative claim."""
    return _claim_state(profile_raw) == "none"


def _claim_reviewed_negative(profile_raw: Any) -> bool:
    """True iff the stored profile carries the reviewed-negative attestation.

    The signal is ``state == "none"`` plus ``reviewed_negative: true`` —
    stamped only by the ``db_claim.amend`` workflow at amendment time.
    Missing profile, malformed JSON, the bare implicit default
    ``{"state":"none"}``, and declared profiles all yield False — the
    gate behaves as if no amendment ever ran.
    """
    parsed = _parse_profile(profile_raw)
    if parsed is None:
        return False
    return is_reviewed_negative(parsed)


__all__ = [
    "_claim_is_declared",
    "_claim_is_none",
    "_claim_reviewed_negative",
    "_claim_state",
]
