"""Teaching-surface regression coverage for workflow item entry.

These tests prove the rendered teaching artifacts (the ``main_agent``
packet, every Bash-capable ``*_agent`` packet, the function-inventory
data, and the surrounding doctrine docs) carry the workflow-selected,
typed entry-surface rule before the lower-level mutation APIs.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import schema_api_context, schema_api_context_seed as seed
from yoke_core.domain.function_inventory_data import RETAINED_TERMINAL_BOUNDARIES


# ---------------------------------------------------------------------------
# Packet teaching — `core` topic and every role
# ---------------------------------------------------------------------------


_ENTRY_TOKENS = ("Work-item entry surfaces", "/yoke idea", "harness_skill")


def _core_body() -> str:
    return schema_api_context.render_topic_packet("core")


def test_core_topic_packet_carries_item_entry_doctrine() -> None:
    body = _core_body()
    for token in _ENTRY_TOKENS:
        assert token in body, f"core packet missing token: {token}"


def test_core_topic_packet_teaches_items_create_scaffolding_gate() -> None:
    body = _core_body()
    assert "yoke items create" in body
    assert "idea mode" in body
    assert "yoke dash TITLE INSTRUCTION" in body
    assert "yoke task TITLE INSTRUCTION" in body


def test_item_entry_block_renders_before_function_call_surface() -> None:
    """The rule appears before lower-level API affordances."""
    body = _core_body()
    intake_pos = body.find("Work-item entry surfaces")
    fn_call_pos = body.find("Registered writes")
    assert intake_pos != -1
    assert fn_call_pos != -1
    assert intake_pos < fn_call_pos, (
        "item-entry doctrine should render before the function-call "
        "surface block so agents see it first"
    )


def test_authoring_role_packets_inherit_entry_and_other_roles_discover_depth() -> None:
    """Creation guidance precedes authoring; other roles inspect it on demand."""
    for role in seed.ROLE_TOPICS:
        body = schema_api_context.render_role_packet(role)
        if role not in ("main_agent", "architect_agent"):
            assert "Work-item entry surfaces" not in body
            assert (
                f"yoke packets render --role {role} --topic core --detail full" in body
            )
            body = schema_api_context.render_topic_packet("core", role=role)
        for token in _ENTRY_TOKENS:
            assert token in body, f"role {role!r} packet missing token: {token}"


# ---------------------------------------------------------------------------
# Function inventory retained-boundary classification
# ---------------------------------------------------------------------------


def test_item_creation_is_not_a_retained_boundary() -> None:
    """Item creation must not be classified as agent-facing retained."""
    forbidden_categories = {"agent_terminal", "retained_terminal_create"}
    for boundary in RETAINED_TERMINAL_BOUNDARIES:
        surface_lc = boundary.surface.lower()
        # No retained boundary should advertise item creation as a sanctioned
        # terminal recipe. (Creation flows through `/yoke idea`.)
        assert "items add" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `items add` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert "backlog-cli add" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `backlog-cli add` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert "post /v1/items" not in surface_lc, (
            f"retained boundary {boundary.surface!r} names `POST /v1/items` — "
            "creation belongs to /yoke idea, not a retained terminal"
        )
        assert boundary.category not in forbidden_categories


# ---------------------------------------------------------------------------
# Shared project doctrine — AGENTS.md
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def test_agents_md_carries_item_entry_rule() -> None:
    body = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")
    assert "Work-item entry surfaces" in body
    assert "/yoke idea" in body
    assert "harness_skill" in body


# ---------------------------------------------------------------------------
# Canonical subagent bodies — architect + boss
# ---------------------------------------------------------------------------


_BASH_CAPABLE_AGENTS = (
    "engineer.md",
    "tester.md",
    "architect.md",
    "simulator.md",
    "boss.md",
)


def test_every_bash_capable_agent_body_teaches_item_entry() -> None:
    """Every Bash-capable canonical body routes item creation through
    ``/yoke idea`` instead of lower-level create surfaces.
    """
    agents_dir = _repo_root() / "runtime" / "agents"
    for name in _BASH_CAPABLE_AGENTS:
        body = (agents_dir / name).read_text(encoding="utf-8")
        lower = body.lower()
        assert "/yoke idea" in body, f"{name} missing /yoke idea"
        assert (
            "do not call `backlog-cli add`" in lower
            or "do not call lower-level create surfaces" in lower
            or "do not create work items yourself" in lower
        ), f"{name} missing explicit item-entry teaching"
