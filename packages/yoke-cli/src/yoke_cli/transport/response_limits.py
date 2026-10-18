"""Shared time and byte ceilings for hosted JSON transports."""

from __future__ import annotations

from yoke_contracts.read_deadline import FUNCTION_RESPONSE_TIMEOUT_SECONDS


DEFAULT_JSON_RESPONSE_LIMIT_BYTES = 4 * 1024 * 1024
BUNDLE_JSON_RESPONSE_LIMIT_BYTES = 16 * 1024 * 1024
SMALL_JSON_RESPONSE_LIMIT_BYTES = 64 * 1024

DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS = FUNCTION_RESPONSE_TIMEOUT_SECONDS
ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS = 20.0
# A run create walks every member's containment and takes over the previous
# run, so it grows with run size (33 s for 21 members). The hosted path allows
# 70 s (the webapp's tenant upstream-call budget, under nginx's 75 s read
# timeout on the function route); stay below the lower cap.
DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS = 60.0


__all__ = [
    "BUNDLE_JSON_RESPONSE_LIMIT_BYTES",
    "DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS",
    "DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS",
    "DEFAULT_JSON_RESPONSE_LIMIT_BYTES",
    "ONBOARD_JSON_REQUEST_TIMEOUT_SECONDS",
    "SMALL_JSON_RESPONSE_LIMIT_BYTES",
]
