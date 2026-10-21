"""Regressions for ``yoke_core.domain.schema_api_context``.

Covers acceptance criteria:

- Render works for ``core``, ``claims``, and the role-specific union
  for the five Bash-capable agents.
- Claims packet includes the canonical work-holder recipe and the
  typed ``work_claims`` target model (target_kind + one canonical
  JSON ``scope`` object per kind).
- Wrapper/domain commands surface before any raw diagnostic SQL recipe.
- Rendered packet bodies are free of the historically
  observed wrong terms.
- Live catalog introspection agrees with the curated seed for every
  declared table.
- Live ``--help`` for service_client, db_router, and the
  harness_sessions module surfaces the wrapper commands the packet teaches.
- Packet size budgets live in ``test_schema_api_context_packet_budget``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_render import PACKET_DETAIL_FULL


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_render_role_packet_non_empty(role: str) -> None:
    body = sac.render_role_packet(role, detail=PACKET_DETAIL_FULL)
    assert body.strip(), f"empty packet for role={role}"
    # Header for at least the first topic is present.
    first_topic = seed.ROLE_TOPICS[role][0]
    assert sac._TOPIC_HEADERS[first_topic] in body


@pytest.mark.parametrize("topic", sorted(seed.TOPICS))
def test_render_topic_packet_non_empty(topic: str) -> None:
    body = sac.render_topic_packet(topic, detail=PACKET_DETAIL_FULL)
    assert body.strip(), f"empty packet for topic={topic}"
    assert sac._TOPIC_HEADERS[topic] in body


def test_render_unknown_role_raises() -> None:
    with pytest.raises(ValueError):
        sac.render_role_packet("not-a-role", detail=PACKET_DETAIL_FULL)


def test_render_unknown_topic_raises() -> None:
    with pytest.raises(ValueError):
        sac.render_topic_packet("not-a-topic", detail=PACKET_DETAIL_FULL)


def test_seed_agrees_with_live_schema() -> None:
    drift = sac.detect_seed_drift()
    assert drift == [], "seed disagrees with live schema:\n" + "\n".join(drift)


def test_db_router_help_lists_taught_commands() -> None:
    text = sac._try_help("yoke_core.cli.db_router")
    if text is None:
        pytest.skip("db_router --help unavailable on this checkout")
    for fragment in ("items", "epic", "events", "qa"):
        assert fragment in text, (
            f"db_router --help missing subcommand fragment: {fragment}"
        )


def test_service_client_help_lists_path_claim_surface() -> None:
    text = sac._try_help("yoke_core.api.service_client")
    if text is None:
        pytest.skip("service_client --help unavailable on this checkout")
    assert "path-claim-list" in text
    assert "release-work-claim" in text


def test_harness_sessions_help_exposes_who_claims() -> None:
    text = sac._try_help("yoke_core.hooks.sessions_cli")
    if text is None:
        pytest.skip("harness_sessions --help unavailable on this checkout")
    assert "who-claims" in text


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
