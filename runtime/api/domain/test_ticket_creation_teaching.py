"""Teaching-surface regression coverage for idea-only ticket intake.

These tests prove the rendered teaching artifacts (the ``main_agent``
packet, every Bash-capable ``*_agent`` packet, the function-inventory
data, and the surrounding doctrine docs) actually carry the
``/yoke idea`` ticket-intake rule before the lower-level item /
body / claim / REST APIs they're meant to gate.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import schema_api_context, schema_api_context_seed as seed
from yoke_core.domain.function_inventory_data import RETAINED_TERMINAL_BOUNDARIES


# ---------------------------------------------------------------------------
# Packet teaching — `core` topic and every role
# ---------------------------------------------------------------------------


_IDEA_TOKENS = ("Ticket intake", "/yoke idea")


def _core_body() -> str:
    return schema_api_context.render_topic_packet("core")


def test_core_topic_packet_carries_ticket_intake_doctrine() -> None:
    body = _core_body()
    for token in _IDEA_TOKENS:
        assert token in body, f"core packet missing token: {token}"


def test_ticket_intake_block_renders_before_function_call_surface() -> None:
    """AC-1: the rule must appear BEFORE lower-level API affordances."""
    body = _core_body()
    intake_pos = body.find("Ticket intake")
    fn_call_pos = body.find("Function-call surface")
    assert intake_pos != -1
    assert fn_call_pos != -1
    assert intake_pos < fn_call_pos, (
        "ticket-intake doctrine should render before the function-call "
        "surface block so agents see it first"
    )


def test_every_role_packet_inherits_ticket_intake_doctrine() -> None:
    """AC-2: main_agent and every *_agent packet contain the rule."""
    for role in seed.ROLE_TOPICS:
        body = schema_api_context.render_role_packet(role)
        for token in _IDEA_TOKENS:
            assert token in body, (
                f"role {role!r} packet missing token: {token}"
            )


# ---------------------------------------------------------------------------
# Function inventory retained-boundary classification
# ---------------------------------------------------------------------------


def test_item_creation_is_not_a_retained_boundary() -> None:
    """AC-4: item creation must not be classified as agent-facing retained."""
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
# Doctrine docs — AGENTS.md and CODEX.md
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def test_agents_md_carries_ticket_intake_rule() -> None:
    body = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")
    assert "Ticket intake" in body
    assert "/yoke idea" in body
    assert "intake-provenance check" in body


def test_codex_md_carries_ticket_intake_rule() -> None:
    body = (_repo_root() / "CODEX.md").read_text(encoding="utf-8")
    assert "Ticket intake" in body
    assert "/yoke idea" in body
    assert "intake-provenance check" in body


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


def test_every_bash_capable_agent_body_teaches_idea_intake() -> None:
    """AC-3: every Bash-capable canonical agent body must instruct the
    agent to report new work for ``/yoke idea`` rather than creating
    tickets directly. Phrasing varies (test-isolation bullet for
    engineer/tester/simulator; standalone bullet for architect/boss);
    the assertion looks for the shared anchor phrase.
    """
    agents_dir = _repo_root() / "runtime" / "agents"
    for name in _BASH_CAPABLE_AGENTS:
        body = (agents_dir / name).read_text(encoding="utf-8")
        lower = body.lower()
        assert "/yoke idea" in body, f"{name} missing /yoke idea"
        assert (
            "do not create tickets" in lower
            or "do not call `backlog-cli add`" in lower
        ), f"{name} missing explicit do-not-create-tickets teaching"
