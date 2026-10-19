"""Reading a machine-authorization server's refusals and poll retry timing."""

from __future__ import annotations

import math
import time
from email.utils import parsedate_to_datetime
from typing import Mapping

from yoke_contracts.machine_authorization import (
    RETRYABLE_POLL_ERRORS,
    HostedMachineAuthorizationError,
    MachineAuthorizationRefused,
)


def recovery(response: object) -> str:
    if isinstance(response, MachineAuthorizationRefused) and response.recovery_text:
        return response.recovery_text
    return "inspect the server refusal and restart connection, or ask its operator for help"


def raise_admission_refusal(payload: object, status: int) -> None:
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if status == 429 and error in {
        "authorization_start_rate_limited",
        "authorization_client_capacity",
        "authorization_capacity",
    }:
        raise HostedMachineAuthorizationError(
            f"{error}: finish pending machine approvals or wait for the server's admission budget to recover, then reconnect"
        ) from None


def poll_is_retryable(status: int, error: object) -> bool:
    expected_error = RETRYABLE_POLL_ERRORS.get(status)
    return expected_error is not None and expected_error == error


def poll_retry_delay(headers: Mapping[str, str], interval: int) -> float:
    raw = next(
        (value for key, value in headers.items() if key.casefold() == "retry-after"),
        "",
    )
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(raw).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return float(interval)
    return max(float(interval), seconds) if math.isfinite(seconds) else float(interval)


__all__ = [
    "poll_is_retryable",
    "poll_retry_delay",
    "raise_admission_refusal",
    "recovery",
]
