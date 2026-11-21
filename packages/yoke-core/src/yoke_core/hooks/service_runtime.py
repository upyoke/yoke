"""Supply hook operations to the service routes."""

from yoke_core.hooks.observation_batch import persist_observation_batch, request_payload
from yoke_core.hooks.session_model_attestation_write import confirmed_served_model
from yoke_core.hooks.session_title import confirmed_title
from yoke_core.hooks.session_turn_posture_tail import persist_authorization_denied_turn_end

__all__ = [
    "confirmed_served_model",
    "confirmed_title",
    "persist_authorization_denied_turn_end",
    "persist_observation_batch",
    "request_payload",
]
