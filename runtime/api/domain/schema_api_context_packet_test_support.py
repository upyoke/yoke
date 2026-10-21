"""Expected anchors shared by schema API-context packet tests."""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain import schema_api_context
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


JSON_NESTED_COLUMNS_REQUIRED = (
    "items.db_mutation_profile",
    "items.db_compatibility_attestation",
    "harness_sessions.offer_envelope",
    "qa_requirements.capability_requirements",
    "qa_requirements.success_policy",
)
NEW_HARNESS_SESSION_COLUMNS = (
    "recent_item_id",
    "recent_item_status",
    "recent_item_recorded_at",
    "offer_envelope",
    "mode",
    "executor_surface",
)


def main_body() -> str:
    """Render canonical teaching independently of ambient fixture databases."""
    with patch.object(schema_api_context, "_try_live_schema", return_value=None):
        return "\n".join(
            schema_api_context.render_topic_packet(
                topic, role="main_agent", detail=PACKET_DETAIL_FULL
            )
            for topic in schema_api_context.seed.ROLE_TOPICS["main_agent"]
        )
