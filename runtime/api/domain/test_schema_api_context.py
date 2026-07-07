"""Regressions for ``yoke_core.domain.schema_api_context``.

Covers acceptance criteria:

- AC-1: render works for ``core``, ``claims``, and the role-specific union
  for the five Bash-capable agents.
- AC-2: claims packet includes the canonical work-holder recipe and the
  typed ``work_claims`` target model (target_kind + specialized columns).
- AC-3: wrapper/domain commands surface before any raw diagnostic SQL recipe.
- AC-11 / AC-21: rendered packet bodies are free of the historically
  observed wrong terms.
- AC-12: live catalog introspection agrees with the curated seed for every
  declared table.
- AC-13: live ``--help`` for service_client, db_router, and the
  harness_sessions module surfaces the wrapper commands the packet teaches.
- AC-14 / AC-22: per-role and aggregate packet sizes stay within budget.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_render_role_packet_non_empty(role: str) -> None:
    body = sac.render_role_packet(role)
    assert body.strip(), f"empty packet for role={role}"
    # Header for at least the first topic is present.
    first_topic = seed.ROLE_TOPICS[role][0]
    assert sac._TOPIC_HEADERS[first_topic] in body


@pytest.mark.parametrize("topic", sorted(seed.TOPICS))
def test_render_topic_packet_non_empty(topic: str) -> None:
    body = sac.render_topic_packet(topic)
    assert body.strip(), f"empty packet for topic={topic}"
    assert sac._TOPIC_HEADERS[topic] in body


def test_render_unknown_role_raises() -> None:
    with pytest.raises(ValueError):
        sac.render_role_packet("not-a-role")


def test_render_unknown_topic_raises() -> None:
    with pytest.raises(ValueError):
        sac.render_topic_packet("not-a-topic")


def test_claims_packet_includes_work_holder_recipe() -> None:
    body = sac.render_topic_packet("claims")
    assert "yoke claims work holder-get YOK-N" in body
    assert "claims.work.holder_get" in body


def test_claims_packet_includes_typed_target_model() -> None:
    body = sac.render_topic_packet("claims")
    # target_kind plus the four specialized columns the typed model uses.
    for column in (
        "target_kind",
        "item_id",
        "epic_id",
        "task_num",
        "process_key",
        "conflict_group",
    ):
        assert column in body, f"claims packet missing typed-target column: {column}"


def test_core_packet_wrappers_precede_raw_sql() -> None:
    body = sac.render_topic_packet("core")
    wrapper_idx = body.index("items get YOK-N")
    raw_sql_idx = body.index("Audited raw diagnostic read")
    assert wrapper_idx < raw_sql_idx, (
        "raw diagnostic SQL must come AFTER wrapper command list — "
        "agents must reach for wrappers first"
    )


def test_core_packet_teaches_cli_additive_transform_recipe() -> None:
    """Additive transforms are executable through the CLI adapter while
    still naming the underlying function family as the contract.

    Progress Log append, append-addendum, and section-upsert all use
    registered ``yoke`` adapters.
    """

    body = sac.render_topic_packet("core")
    assert "items.structured_field" in body
    assert "append-addendum" in body
    assert "section-upsert" in body
    assert "yoke items progress-log append" in body
    assert "yoke items structured-field append-addendum" in body
    assert "yoke items structured-field section-upsert" in body
    assert "--json" in body


def test_core_packet_teaches_cli_structured_field_replace() -> None:
    """The structured-field replace mutation is executable through the
    canonical ``yoke`` CLI adapter; the packet names the function id
    as the underlying contract but must not teach HTTP or direct-dispatch
    shapes."""

    body = sac.render_topic_packet("core")
    assert "items.structured_field.replace" in body
    assert "yoke items structured-field replace YOK-N" in body


def test_core_packet_teaches_lifecycle_status_and_inventory_surface() -> None:
    """The core packet teaches the canonical ``yoke lifecycle
    transition`` shape plus the function id, and routes registry
    inspection through the inventory CLI rather than a direct
    runtime.api import."""

    body = sac.render_topic_packet("core")
    assert "yoke lifecycle transition YOK-N --to refined-idea" in body
    assert "lifecycle.transition.execute" in body
    assert "function=lifecycle.transition target" not in body
    assert "--stdin < PATH" in body
    assert "atlas_render_docs check" in body
    assert 'python3 -c "\nfrom runtime.api' not in body


def test_packets_do_not_teach_blocked_agent_surface_shapes() -> None:
    """AC-5: rendered packets must not teach shapes the new agent-surface
    lints warn on. Function ids can be named, but executable recipes must
    stay on CLI adapters."""

    packet = "\n".join(
        sac.render_topic_packet(topic)
        for topic in ("core", "claims", "qa", "project")
    )
    banned = (
        "curl -sS",
        "api_server start",
        "localhost:8000",
        "localhost:8765",
        "127.0.0.1:8765",
        "POST /v1/functions/call",
        "python3 -c \"\nfrom runtime.api",
    )
    for token in banned:
        assert token not in packet


def test_core_packet_teaches_cli_epic_task_body_replace() -> None:
    """Epic task body / metadata mutations are taught through retained
    CLI adapters, with the function family named as the underlying owner."""

    body = sac.render_topic_packet("core")
    assert "workflow_item.epic_task" in body
    assert "yoke workflow-item epic-task body-replace" in body
    assert "yoke workflow-item epic-task metadata-update" in body
    assert "/yoke amend" in body
    assert "yoke workflow-item epic-progress-note append" in body


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_role_packet_contains_no_stale_terms(role: str) -> None:
    body = sac.render_role_packet(role)
    for stale in seed.STALE_TERMS:
        assert stale not in body, (
            f"role={role} packet contains stale term '{stale}'. "
            "Rewrite the seed note with indirect language so the bare "
            "wrong name does not appear in agent context."
        )


_CANONICAL_LIVE_NAMES_BY_TOPIC = {
    "core": (
        "epic_tasks",
        "epic_progress_notes",
        "events",
        "envelope",
        "event_name",
        "shepherd dependency-list",
    ),
    "claims": (
        "harness_sessions",
        "current_item_id",
        "work_claims",
        "target_kind",
        "process_key",
        "conflict_group",
        "path_claims",
        "claims work holder-get",
    ),
    "auth": (
        "organizations",
        "actor_org_roles",
        "org_id",
        "actor_project_roles",
        "role_permissions",
        "permission_id",
    ),
    "qa": (
        "qa_requirements",
        "qa_runs",
        "qa_requirement_id",
        "executor_type",
        "yoke qa requirement list",
        "yoke qa gate-summary",
    ),
    "project": (
        "project_structure",
        "command_definitions",
        "yoke project-structure command-definitions get",
        # AC-2 / AC-4 positive teaching: project_capabilities + deployment JOINs.
        "SELECT type, settings FROM project_capabilities",
        "JOIN deployment_run_items dri ON dri.run_id = dr.id",
        "SELECT id, stages FROM deployment_flows",
    ),
}


def test_project_topic_packet_avoids_phantom_columns() -> None:
    """AC-11: rewritten notes must not mention phantom columns."""
    body = sac.render_topic_packet("project")
    for phantom in (
        "deployment_runs" ".item_id",
        "deployment_runs" ".run_id",
        "deployment_run_items" ".id",
        "project_capabilities" ".key",
        "project_capabilities" ".value",
        "project_capabilities" ".capability",
    ):
        assert phantom not in body, f"phantom column '{phantom}' resurfaced"


@pytest.mark.parametrize("topic", sorted(seed.TOPICS))
def test_topic_packet_surfaces_canonical_live_names(topic: str) -> None:
    body = sac.render_topic_packet(topic)
    for live_name in _CANONICAL_LIVE_NAMES_BY_TOPIC[topic]:
        assert live_name in body, (
            f"topic={topic} packet missing canonical live name '{live_name}' — "
            "the regression cheat sheet enumerates this; if the live schema "
            "changed, update the seed in lockstep with the schema."
        )


def test_seed_agrees_with_live_schema() -> None:
    drift = sac.detect_seed_drift()
    assert drift == [], (
        "seed disagrees with live schema:\n" + "\n".join(drift)
    )


def test_db_router_help_lists_taught_commands() -> None:
    text = sac._try_help("yoke_core.cli.db_router")
    if text is None:
        pytest.skip("db_router --help unavailable on this checkout")
    for fragment in ("items", "epic", "events", "qa"):
        assert fragment in text, f"db_router --help missing subcommand fragment: {fragment}"


def test_service_client_help_lists_path_claim_surface() -> None:
    text = sac._try_help("yoke_core.api.service_client")
    if text is None:
        pytest.skip("service_client --help unavailable on this checkout")
    assert "path-claim-list" in text
    assert "release-work-claim" in text


def test_harness_sessions_help_exposes_who_claims() -> None:
    text = sac._try_help("runtime.harness.harness_sessions")
    if text is None:
        pytest.skip("harness_sessions --help unavailable on this checkout")
    assert "who-claims" in text


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_role_packet_within_size_budget(role: str) -> None:
    size, budget = sac.check_role_packet_size(role)
    assert size <= budget, (
        f"role={role} packet has {size} lines, budget is {budget}. "
        "Either trim the seed (preferred — packet content is for fast "
        "agent reference, not a comprehensive schema doc) or increase "
        "PACKET_LINE_BUDGET_PER_ROLE in schema_api_context_seed.py with "
        "an explicit rationale."
    )


def test_aggregate_packet_size_within_budget() -> None:
    total, budget = sac.check_aggregate_size()
    assert total <= budget, (
        f"aggregate packet size is {total} lines, budget is {budget}. "
        "See PACKET_LINE_BUDGET_AGGREGATE in schema_api_context_seed.py."
    )


def test_every_role_topic_is_known() -> None:
    for role, topics in seed.ROLE_TOPICS.items():
        for topic in topics:
            assert topic in seed.TOPICS, f"role={role} references unknown topic {topic}"


def test_every_topic_has_at_least_one_table() -> None:
    for topic in seed.TOPICS:
        assert seed.TOPIC_TABLES.get(topic), f"topic={topic} surfaces zero tables"


def test_every_topic_table_is_in_canonical_set() -> None:
    for topic, tables in seed.TOPIC_TABLES.items():
        for table in tables:
            assert table in seed.CANONICAL_TABLES, (
                f"topic={topic} surfaces table '{table}' that is not in "
                "CANONICAL_TABLES"
            )


def test_drift_error_raised_on_disagreement(monkeypatch: pytest.MonkeyPatch) -> None:
    """When live schema reports a column type that disagrees with the seed,
    ``_resolve_columns`` raises DriftError instead of silently shipping
    the curated value."""

    fake_table = "harness_sessions"

    def fake_live(table: str) -> list[tuple[str, str]]:
        # Return a deliberately-wrong type for the first declared column.
        first_name = seed.CANONICAL_TABLES[table]["columns"][0][0]
        return [(first_name, "WRONG_TYPE")] + [
            (n, t) for (n, t) in seed.CANONICAL_TABLES[table]["columns"][1:]
        ]

    monkeypatch.setattr(sac, "_try_live_schema", fake_live)

    with pytest.raises(sac.DriftError):
        sac._resolve_columns(fake_table)
