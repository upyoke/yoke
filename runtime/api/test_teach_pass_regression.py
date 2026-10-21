"""Durable canonical-form reachability regression.

Backstop for the rendered ``main_agent`` packet plus the three denial
bodies an agent reads on a failing path-claim operation. The packet
renders once at module scope; storage-backed gate checks use disposable
Postgres fixtures.
"""

from __future__ import annotations

import re

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.path_claim_bash_guard_narrative import (
    worktree_unresolved_narrative,
)
from yoke_core.domain.path_claim_register import compose_overlap_denial
from yoke_core.domain.path_claim_target_resolver import ClaimContext
from yoke_core.domain.yok_n_parser import parse_item_id
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL

_RENDERED_BODY: str = "\n".join(
    sac.render_topic_packet(topic, detail=PACKET_DETAIL_FULL)
    for topic in sac.seed.ROLE_TOPICS["main_agent"]
)


@pytest.fixture(scope="module")
def body() -> str:
    return _RENDERED_BODY


# Canonical columns that must render adjacent to their owning table.
_REQUIRED_TABLE_COLUMNS = {
    "harness_sessions": (
        "session_id",
        "executor",
        "execution_level",
        "offer_envelope",
        "current_item_id",
        "actor_id",
        "last_heartbeat",
        "ended_at",
    ),
    "path_claims": (
        "id",
        "state",
        "mode",
        "owner_kind",
        "owner_item_id",
        "owner_session_id",
        "owner_work_claim_id",
        "registered_by_actor_id",
        "registered_by_session_id",
        "integration_target",
        "activated_at",
        "released_at",
    ),
    "path_targets": (
        "id",
        "project_id",
        "kind",
        "path_string",
        "generation",
        "materialization_state",
        "planned_by_item_id",
        "planned_by_claim_id",
    ),
    "path_claim_targets": ("id", "claim_id", "target_id", "declared_at"),
    "path_claim_amendments": (
        "id",
        "claim_id",
        "amended_at",
        "amendment_kind",
        "payload",
        "reason",
    ),
    "item_sections": ("item_id", "section_name", "content", "ordering", "source"),
}


@pytest.mark.parametrize("table, columns", list(_REQUIRED_TABLE_COLUMNS.items()))
def test_columns_render_adjacent_to_owning_table(
    body: str, table: str, columns: tuple[str, ...]
) -> None:
    for column in columns:
        pat = re.compile(rf"`{re.escape(table)}`.*?\b{re.escape(column)}\b", re.DOTALL)
        assert pat.search(body), (
            f"{table}.{column} must render adjacent to its owning table."
        )


def test_packet_names_every_registered_write(body: str) -> None:
    for function in sac.seed.AGENT_WRITE_FUNCTION_IDS:
        assert f"`{function}`" in body


_JSON_NESTED_COLUMNS_REQUIRED = (
    "items.db_mutation_profile",
    "items.db_compatibility_attestation",
    "harness_sessions.offer_envelope",
    "qa_requirements.capability_requirements",
    "qa_requirements.success_policy",
)


@pytest.mark.parametrize("column", _JSON_NESTED_COLUMNS_REQUIRED)
def test_json_nested_schema_renders(body: str, column: str) -> None:
    assert column in body, (
        f"JSON-nested-field schema for {column} must render in the packet."
    )


def test_parse_item_id_accepts_int_internal_id_and_rejects_unscoped_strings() -> None:
    assert parse_item_id(123) == 123
    with pytest.raises(ValueError):
        parse_item_id("123")
    with pytest.raises(ValueError):
        parse_item_id("YOK-123")


def test_worktree_unresolved_denial_embeds_preflight_command() -> None:
    """WORKTREE_UNRESOLVED → preflight (never widen)."""

    # The live lookup renders public_ref from its connection and puts it on
    # the context; the recipe has to carry a ref the operator can paste.
    ctx = ClaimContext(
        claim_id=42,
        item_id=123,
        integration_target="main",
        state="active",
        covered_paths=("AGENTS.md",),
        worktree_path=None,
        public_ref="YOK-123",
    )
    narrative = worktree_unresolved_narrative(
        tool_kind="Edit",
        target_path="AGENTS.md",
        ctx=ctx,
    )
    assert (
        "yoke dev run -- python3 -m yoke_core.domain.worktree_preflight --item YOK-123"
    ) in narrative
    assert "item_worktrees row" in narrative
    assert "path-claim-widen" not in narrative
    assert "path-claims widen" not in narrative


def test_path_claim_register_overlap_denial_requires_workflow_evidence() -> None:
    # No connection here, so nothing can resolve a reference; the denial
    # says that plainly rather than assembling one from the internal id.
    body_text = compose_overlap_denial(
        item_id=123,
        integration_target="main",
        candidate_target_ids=[],
        base_message="candidate overlaps another active claim",
        conn=None,
    )
    assert "BLOCKED: path-claim register overlap on item " in body_text
    assert "unresolved item ref" in body_text
    assert "123" not in body_text
    assert "Recovery: Read the item workflow" in body_text
    assert "yoke say --steering" in body_text
    assert "/yoke refine" not in body_text
    assert "coordination-decision-build" not in body_text
