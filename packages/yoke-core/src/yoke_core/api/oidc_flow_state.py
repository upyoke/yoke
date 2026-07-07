"""Replay-safe state + nonce record for one browser sign-in flow.

The authorization-code flow needs the ``state`` (CSRF binding between
the browser that started the flow and the callback) and the ``nonce``
(binding between the authorization request and the id_token) to survive
the round-trip through the provider. Both ride an HMAC-signed,
short-lived record stored in an HttpOnly browser cookie — no database
table, no server-side session.

The MAC key is derived from the client secret, so every server worker
and restart verifies the same records without shared storage; rotating
the client secret invalidates in-flight sign-ins, which is the desired
behavior on rotation anyway. The callback route deletes the cookie after
use, so a captured callback URL cannot be replayed from a browser that
never started the flow.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from yoke_core.api.oidc_config import OidcConfig, OidcError


#: How long a started sign-in flow may take before its state record is
#: stale and the browser must restart from the sign-in link.
FLOW_STATE_TTL_S = 600


class OidcFlowStateError(OidcError):
    """The flow-state record is missing, tampered, stale, or mismatched."""


@dataclass(frozen=True)
class FlowState:
    """One started sign-in flow: the CSRF ``state``, the id_token
    ``nonce``, and the signed cookie record that round-trips them."""

    state: str
    nonce: str
    cookie_value: str


def _mac_key(config: OidcConfig) -> bytes:
    return hashlib.sha256(
        b"oidc-flow-state-mac-key:" + config.client_secret.encode("utf-8")
    ).digest()


def _signature(config: OidcConfig, payload: str) -> str:
    return hmac.new(
        _mac_key(config), payload.encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def mint_flow_state(config: OidcConfig) -> FlowState:
    """Start one sign-in flow: fresh random state + nonce, signed record.

    ``token_urlsafe`` values never contain ``.``, so the dot-delimited
    record parses unambiguously.
    """
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    expires_epoch = int(time.time()) + FLOW_STATE_TTL_S
    payload = f"{state}.{nonce}.{expires_epoch}"
    cookie_value = payload + "." + _signature(config, payload)
    return FlowState(state=state, nonce=nonce, cookie_value=cookie_value)


def verify_flow_state(
    config: OidcConfig,
    *,
    cookie_value: str,
    state_param: str,
) -> str:
    """Check the signed record against the callback's ``state``; return
    the flow's nonce.

    Every failure mode (missing, malformed, tampered, expired, state
    mismatch) raises the same exception type so the HTTP layer answers
    one generic "restart sign-in" and a probing client learns nothing
    from the split.
    """
    parts = str(cookie_value or "").split(".")
    if len(parts) != 4:
        raise OidcFlowStateError("sign-in flow state is missing or malformed")
    state, nonce, expires_text, signature = parts
    payload = f"{state}.{nonce}.{expires_text}"
    if not hmac.compare_digest(signature, _signature(config, payload)):
        raise OidcFlowStateError("sign-in flow state failed verification")
    try:
        expires_epoch = int(expires_text)
    except ValueError as exc:
        raise OidcFlowStateError("sign-in flow state is malformed") from exc
    if time.time() > expires_epoch:
        raise OidcFlowStateError("sign-in flow state is stale")
    if not state_param or not hmac.compare_digest(state, str(state_param)):
        raise OidcFlowStateError("sign-in flow state does not match")
    return nonce


__all__ = [
    "FLOW_STATE_TTL_S",
    "FlowState",
    "OidcFlowStateError",
    "mint_flow_state",
    "verify_flow_state",
]
