"""Foundation contracts for fleet messaging, launches, and relays."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control import (
    SESSION_SURFACE_CAPABILITIES,
    SESSION_CONTROL_FUNCTION_IDS,
    RecipientSelector,
)
from yoke_core.domain.session_control_schema import (
    SESSION_CONTROL_TABLES,
    create_session_control_tables,
)


def test_capability_facts_cover_the_closed_surface_vocabulary() -> None:
    assert set(SESSION_SURFACE_CAPABILITIES) == set(KNOWN_SURFACE_LABELS)


def test_registered_function_vocabulary_uses_product_verbs_only() -> None:
    assert "session_control.message.send" in SESSION_CONTROL_FUNCTION_IDS
    assert "session_control.launch.create" in SESSION_CONTROL_FUNCTION_IDS
    assert "session_control.relay.claim" in SESSION_CONTROL_FUNCTION_IDS
    assert not any(
        native in function_id
        for function_id in SESSION_CONTROL_FUNCTION_IDS
        for native in ("queue", "steer", "resume")
    )


@pytest.mark.parametrize(
    "surface, active, idle, stopped",
    [
        ("claude-cli", "private", "private", "private"),
        ("codex-cli", "none", "none", "supported"),
        ("cursor-cli", "none", "supported", "supported"),
    ],
)
def test_cli_messageability_matches_pinned_evidence(
    surface: str,
    active: str,
    idle: str,
    stopped: str,
) -> None:
    capability = SESSION_SURFACE_CAPABILITIES[surface]
    assert capability.message_active == active
    assert capability.message_idle == idle
    assert capability.message_stopped == stopped


def test_recipient_selector_requires_an_anchor_and_closed_surfaces() -> None:
    selector = RecipientSelector(
        projects=["yoke"],
        executor_surfaces=["codex-cli"],
        liveness=["stopped"],
    )
    assert selector.projects == ["yoke"]

    with pytest.raises(ValidationError, match="recipient anchor"):
        RecipientSelector(executor_surfaces=["codex-cli"])
    with pytest.raises(ValidationError, match="unknown executor surfaces"):
        RecipientSelector(universe=True, executor_surfaces=["invented"])


def test_session_control_schema_is_additive_and_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE actors (id INTEGER PRIMARY KEY);
        CREATE TABLE projects (id INTEGER PRIMARY KEY);
        CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY);
        """
    )

    create_session_control_tables(conn)
    create_session_control_tables(conn)

    present = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert set(SESSION_CONTROL_TABLES) <= present
