"""Fail-closed parsers for body-free Fleet acceptance evidence."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)


def one_recipient(
    value: Any,
    *,
    session_id: str,
    surface: str,
) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise AcceptanceContractError("recipient_evidence_invalid", surface=surface)
    recipient = value[0]
    if recipient.get("session_id") != session_id:
        raise AcceptanceContractError("recipient_identity_mismatch", surface=surface)
    return recipient


def receipt_count(value: Any, *, surface: str) -> int:
    if isinstance(value, bool):
        raise AcceptanceContractError("receipt_count_invalid", surface=surface)
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise AcceptanceContractError("receipt_count_invalid", surface=surface) from exc
    if count < 0:
        raise AcceptanceContractError("receipt_count_invalid", surface=surface)
    return count


__all__ = ["one_recipient", "receipt_count"]
