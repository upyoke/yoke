"""Backlog status-claim verification for status writes.

`_verify_status_claim` ensures the request session holds the active claim
before a status write proceeds, honoring the `YOKE_CLAIM_BYPASS` and
`YOKE_STATUS_SOURCE` audit escape hatches and emitting
`ClaimVerificationDenied`/`Bypassed` events.
"""

from __future__ import annotations

import os
from typing import Any, Optional, TextIO

from yoke_core.domain import backlog_rendering as _rendering


_STATUS_CLAIM_SESSION_REQUIRED = (
    "request session_id is required for status claim verification"
)


def _verify_status_claim(
    conn: Any,
    item_id: int,
    out: TextIO,
    *,
    session_id: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Verify the request session holds the active claim for a status write."""
    bypass_source = os.environ.get("YOKE_CLAIM_BYPASS", "")
    status_source = os.environ.get("YOKE_STATUS_SOURCE", "")
    if not bypass_source and status_source.startswith("repair-status:"):
        bypass_source = status_source

    request_session_id = str(session_id or "").strip()
    if bypass_source:
        _rendering._emit_event(
            "ClaimVerificationBypassed",
            item_id,
            {
                "bypass_source": bypass_source,
                "session_id": request_session_id or "unknown",
                "work_unit": f"YOK-{item_id}",
            },
            out,
        )
        return True, None

    if not request_session_id:
        _rendering._emit_event(
            "ClaimVerificationDenied",
            item_id,
            {
                "failure_type": "no_session_id",
                "work_unit": f"YOK-{item_id}",
            },
            out,
        )
        return False, _STATUS_CLAIM_SESSION_REQUIRED

    from yoke_core.domain.sessions import get_claim_for_work_unit

    claim = get_claim_for_work_unit(conn, item_id=str(item_id))
    if claim is None:
        _rendering._emit_event(
            "ClaimVerificationDenied",
            item_id,
            {
                "failure_type": "no_active_claim",
                "session_id": request_session_id,
                "work_unit": f"YOK-{item_id}",
            },
            out,
        )
        return False, f"no active claim on YOK-{item_id}"

    claimant_session = str(claim.get("session_id") or "")
    if claimant_session == request_session_id:
        return True, None

    _rendering._emit_event(
        "ClaimVerificationDenied",
        item_id,
        {
            "failure_type": "wrong_session",
            "session_id": request_session_id,
            "claimant_session": claimant_session,
            "work_unit": f"YOK-{item_id}",
        },
        out,
    )
    return False, f"claim held by different session {claimant_session}"


__all__ = ["_verify_status_claim"]
