"""Expected anchors shared by schema API-context packet tests."""

from __future__ import annotations

import re

from yoke_core.domain import schema_api_context
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


JSON_NESTED_COLUMNS_REQUIRED = (
    "items.db_mutation_profile",
    "items.db_compatibility_attestation",
    "harness_sessions.offer_envelope",
    "qa_requirements.capability_requirements",
    "qa_requirements.success_policy",
)
CLI_ANCHORS_REQUIRED = (
    "yoke claims work acquire --item PREFIX-",
    "yoke claims work release --item PREFIX-",
    "yoke claims path register",
    "yoke claims path widen",
    "yoke lifecycle transition",
    "yoke items structured-field replace",
    "yoke items progress-log append",
    "yoke events query",
    "yoke ouroboros field-note append",
    "yoke claims path list --item PREFIX-N",
    "yoke db-claim amend PREFIX-N",
    "--state none",
    "backlog-cli",
    "lifecycle.transition",
    'yoke db read "SELECT 1"',
    "worktree paths db",
    "harness_id",
)
BANNED_CONFABULATIONS = (
    "pt.path",
    "items.item_id",
    "work_claims.state",
    "events.source_id",
)
FORBIDDEN_SESSION_ID_AFFIRMATIVE = re.compile(
    r"(?:`--session-id S`\s+to\s+)?act\s+on\s+another\s+session",
    re.IGNORECASE | re.DOTALL,
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
    """Render the main-agent packet at the depth its teaching lives at.

    Full depth, because these anchors are the per-table and per-command
    notes — the wrong guesses each one corrects. Compact is a strict subset
    that ships at session start; an agent reaches this depth through the
    pointer the compact body closes with.
    """
    return schema_api_context.render_role_packet(
        "main_agent", detail=PACKET_DETAIL_FULL
    )
