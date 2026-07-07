"""Tests for the shared dispatch descriptor module."""

from __future__ import annotations

import pytest

from yoke_core.domain.dispatch_descriptors import (
    DISPATCH_KIND_SUBAGENT,
    REFLECTION_BLOCK,
    ROLE_RESULT_SCHEMA,
    ROLES,
    SUBMISSION_CHECKS_BLOCK,
    VERDICT_PASS_FAIL,
    VERDICT_READY_NOT_READY_CAVEATS,
    VERDICT_SIMULATION,
    DispatchDescriptor,
    render_for_harness,
)
from yoke_core.domain.harness_capability_registry import HARNESS_UNIVERSE


# --------------------------------------------------------------------------- #
# Construction + validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ROLES)
def test_descriptor_constructs_for_every_role(role: str) -> None:
    descriptor = DispatchDescriptor(role=role)
    assert descriptor.role == role
    assert descriptor.dispatch_kind == DISPATCH_KIND_SUBAGENT
    assert descriptor.subagent_type == f"yoke-{role}"


def test_unknown_role_rejected() -> None:
    with pytest.raises(ValueError, match="unknown dispatch role"):
        DispatchDescriptor(role="unknown-role")


def test_unknown_dispatch_kind_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported dispatch_kind"):
        DispatchDescriptor(role="engineer", dispatch_kind="task-fork")


# --------------------------------------------------------------------------- #
# Claude rendering — AC-2: prose-equivalent to hand-authored snippets
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ROLES)
def test_render_claude_emits_subagent_type_line(role: str) -> None:
    descriptor = DispatchDescriptor(role=role)
    rendered = render_for_harness(descriptor, "claude-code")
    assert "Agent tool:" in rendered
    assert f'subagent_type: "yoke-{role}"' in rendered
    assert "prompt: |" in rendered


def test_render_claude_engineer_matches_skill_prose_shape() -> None:
    """The rendered prose matches the engineer snippet in dispatch-context-prompts.md."""
    descriptor = DispatchDescriptor(role="engineer")
    rendered = render_for_harness(descriptor, "claude-code")
    # Hand-authored snippet uses these exact lines verbatim:
    assert "Agent tool:" in rendered
    assert ' subagent_type: "yoke-engineer"' in rendered
    assert " prompt: |" in rendered


def test_render_claude_tester_matches_skill_prose_shape() -> None:
    """The rendered prose matches the tester snippet in dispatch-context-prompts.md."""
    descriptor = DispatchDescriptor(role="tester")
    rendered = render_for_harness(descriptor, "claude-code")
    assert ' subagent_type: "yoke-tester"' in rendered


def test_render_claude_emits_model_override_when_in_extras() -> None:
    """The retry-with-opus extras shape used by conduct's tester dispatch."""
    descriptor = DispatchDescriptor(
        role="tester",
        extras=(("model", "opus"),),
    )
    rendered = render_for_harness(descriptor, "claude-code")
    assert ' model: "opus"' in rendered
    assert ' subagent_type: "yoke-tester"' in rendered


# --------------------------------------------------------------------------- #
# Codex rendering — AC-3: invocation names the adapter path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ROLES)
def test_render_codex_names_adapter_path(role: str) -> None:
    descriptor = DispatchDescriptor(role=role)
    rendered = render_for_harness(descriptor, "codex")
    assert f".codex/agents/yoke-{role}.toml" in rendered
    assert "prompt: |" in rendered


def test_render_codex_includes_model_override() -> None:
    descriptor = DispatchDescriptor(
        role="tester",
        extras=(("model", "opus"),),
    )
    rendered = render_for_harness(descriptor, "codex")
    assert ".codex/agents/yoke-tester.toml" in rendered
    assert ' model: "opus"' in rendered


# --------------------------------------------------------------------------- #
# Harness id validation against HARNESS_UNIVERSE
# --------------------------------------------------------------------------- #


def test_render_rejects_unknown_harness_id() -> None:
    descriptor = DispatchDescriptor(role="engineer")
    with pytest.raises(ValueError, match="unknown harness_id"):
        render_for_harness(descriptor, "unknown-harness")


def test_render_accepts_every_harness_in_universe() -> None:
    descriptor = DispatchDescriptor(role="engineer")
    for harness_id in HARNESS_UNIVERSE:
        rendered = render_for_harness(descriptor, harness_id)
        assert isinstance(rendered, str) and rendered.strip()


# --------------------------------------------------------------------------- #
# Round-trip: parseable-result schema is shared across harnesses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ROLES)
def test_result_schema_present_for_every_role(role: str) -> None:
    descriptor = DispatchDescriptor(role=role)
    schema = descriptor.result_schema
    assert schema, f"role {role!r} has empty result schema"
    # Every Yoke role emits a reflection block at end-of-session.
    assert REFLECTION_BLOCK in schema


def test_result_schema_invariant_across_harnesses() -> None:
    """Both harnesses' renderings reference the SAME parsing schema.

    This is the round-trip contract: a parent skill that parses an engineer
    return uses the same markers regardless of which harness rendered the
    dispatch snippet.
    """
    descriptor = DispatchDescriptor(role="engineer")
    schema_per_harness = {
        harness_id: descriptor.result_schema for harness_id in HARNESS_UNIVERSE
    }
    # Schema is descriptor-owned, not harness-derived; all entries identical.
    assert len(set(schema_per_harness.values())) == 1


def test_engineer_result_schema_contains_submission_checks() -> None:
    descriptor = DispatchDescriptor(role="engineer")
    assert SUBMISSION_CHECKS_BLOCK in descriptor.result_schema


def test_tester_result_schema_contains_verdict_pass_fail() -> None:
    descriptor = DispatchDescriptor(role="tester")
    assert VERDICT_PASS_FAIL in descriptor.result_schema


def test_simulator_result_schema_contains_simulation_verdict() -> None:
    descriptor = DispatchDescriptor(role="simulator")
    assert VERDICT_SIMULATION in descriptor.result_schema


def test_boss_result_schema_contains_ready_not_ready_caveats() -> None:
    descriptor = DispatchDescriptor(role="boss")
    assert VERDICT_READY_NOT_READY_CAVEATS in descriptor.result_schema


def test_role_result_schema_table_covers_every_role() -> None:
    """No role can be rendered without a documented parseable-result shape."""
    assert set(ROLE_RESULT_SCHEMA.keys()) == set(ROLES)
