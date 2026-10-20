"""Durable identity for a submitted host-control result."""

import hmac
from typing import Any, Mapping


def host_control_submission_receipt(
    lease_id: int,
    contract_digest: str,
    *,
    reset_owed_baseline: str | None = None,
) -> dict[str, Any]:
    receipt = {"lease_id": int(lease_id), "contract_digest": str(contract_digest)}
    if reset_owed_baseline is not None:
        receipt["reset_owed_baseline"] = reset_owed_baseline
    return receipt


def host_control_submission_receipt_matches(
    value: Any,
    *,
    lease_id: int,
    contract_digest: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        stored_lease_id = int(value.get("lease_id"))
    except (TypeError, ValueError):
        return False
    stored_digest = value.get("contract_digest")
    return (
        stored_lease_id == int(lease_id)
        and isinstance(stored_digest, str)
        and hmac.compare_digest(stored_digest, str(contract_digest))
    )
