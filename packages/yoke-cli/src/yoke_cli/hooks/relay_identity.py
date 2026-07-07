"""Compatibility shim for product-owned hook identity enrichment."""

from yoke_harness.hooks.identity import (
    REGISTRATION_EVENTS,
    client_entrypoint,
    client_lane,
    client_model,
    relay_identity_payload,
)

__all__ = [
    "REGISTRATION_EVENTS",
    "client_entrypoint",
    "client_lane",
    "client_model",
    "relay_identity_payload",
]
