"""Compatibility facade for hook identity enrichment."""

from yoke_harness.hooks.identity_anchor import record_session_anchor
from yoke_harness.hooks.identity_relay import (
    REGISTRATION_EVENTS,
    client_entrypoint,
    client_lane,
    client_model,
    relay_identity_payload,
)
from yoke_harness.hooks.identity_runtime import (
    detect_entrypoint,
    detect_executor,
    detect_model,
    is_codex,
    resolve_session_id,
    write_runtime_cache,
)

__all__ = [
    "REGISTRATION_EVENTS",
    "client_entrypoint",
    "client_lane",
    "client_model",
    "detect_entrypoint",
    "detect_executor",
    "detect_model",
    "is_codex",
    "record_session_anchor",
    "relay_identity_payload",
    "resolve_session_id",
    "write_runtime_cache",
]
