"""Sessionless authenticated feedback attribution read."""

from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.feedback_attribution import actor_email
from yoke_core.domain.universe_identity import universe_fingerprint


class ProvenanceRequest(BaseModel):
    pass


class ProvenanceResponse(BaseModel):
    universe_fingerprint: str | None
    actor_email: str | None


def handle_get(request):
    with connect() as conn:
        return HandlerOutcome(result_payload={
            "universe_fingerprint": universe_fingerprint(conn),
            "actor_email": actor_email(conn, request.actor.actor_id),
        })


REGISTRATIONS = [{
    "function_id": "feedback.provenance.get", "handler": handle_get,
    "request_model": ProvenanceRequest, "response_model": ProvenanceResponse,
    "minimum_serving_version": "next-release", "stability": "stable",
    "owner_module": "yoke_core.domain.handlers.feedback_provenance",
    "target_kinds": ["global"], "side_effects": [], "emitted_event_names": [],
    "guardrails": [], "adapter_status": "internal", "claim_required_kind": None,
    "ambient_session_required": False,
}]
