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
    stop_denial_continuation_supported,
)
from yoke_core.domain.session_control_schema import (
    create_session_control_tables,
    required_tables,
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
    "surface, active, idle, stopped, stop_continuation, relay_continuation, "
    "liveness_names",
    [
        (
            "claude-cli",
            "private",
            "private",
            "supported",
            "supported",
            "none",
            (),
        ),
        (
            "codex-cli",
            "none",
            "none",
            "supported",
            "supported",
            "none",
            (),
        ),
        (
            "cursor-cli",
            "none",
            "supported",
            "supported",
            "none",
            "none",
            ("cursor-agent", "cursor"),
        ),
    ],
)
def test_cli_messageability_matches_pinned_evidence(
    surface: str,
    active: str,
    idle: str,
    stopped: str,
    stop_continuation: str,
    relay_continuation: str,
    liveness_names: tuple[str, ...],
) -> None:
    capability = SESSION_SURFACE_CAPABILITIES[surface]
    assert capability.message_active == active
    assert capability.message_idle == idle
    assert capability.message_stopped == stopped
    assert capability.stop_denial_continuation == stop_continuation
    assert capability.relay_stop_denial_continuation == relay_continuation
    assert capability.liveness_process_names == liveness_names


@pytest.mark.parametrize(
    ("executor", "surface", "relay_launched", "expected"),
    [
        ("claude", "cli", True, False),
        ("claude-code", "cli", False, True),
        ("codex", "codex-exec", True, False),
        ("codex", "desktop", True, False),
        ("codex", "vscode", False, True),
        ("cursor", "cursor-cli", False, False),
    ],
)
def test_stop_continuation_resolves_relative_and_canonical_surfaces(
    executor: str,
    surface: str,
    relay_launched: bool,
    expected: bool,
) -> None:
    assert (
        stop_denial_continuation_supported(
            executor,
            surface,
            relay_launched=relay_launched,
        )
        is expected
    )


def test_recipient_selector_requires_an_anchor_and_closed_surfaces() -> None:
    selector = RecipientSelector(
        projects=["yoke"],
        executor_surfaces=["codex-cli"],
        liveness=["ended"],
    )
    assert selector.projects == ["yoke"]

    with pytest.raises(ValidationError, match="recipient anchor"):
        RecipientSelector(executor_surfaces=["codex-cli"])
    with pytest.raises(ValidationError, match="unknown executor surfaces"):
        RecipientSelector(universe=True, executor_surfaces=["invented"])
    # A state the resolver never produces would filter to nobody in silence.
    with pytest.raises(ValidationError, match="unknown liveness states"):
        RecipientSelector(universe=True, liveness=["stopped"])


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
    assert set(required_tables()) <= present
    message_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(session_messages)")
    }
    assert "sender_surface" in message_columns
    actor_recipient_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(actor_message_recipients)")
    }
    # One table, two recipient kinds: an actor's read state and a
    # role-addressed steering delivery, each with its own columns.
    assert actor_recipient_columns == {
        "message_id",
        "recipient_kind",
        "actor_id",
        "state",
        "created_at",
        "read_at",
        "expired_at",
        "steering_scope",
        "sender_item_id",
        "project_id",
        "seat_session_id",
        "seat_claim_id",
        "delivered_at",
        "acknowledged_at",
    }
    relay_columns = {
        row[1]: bool(row[3])
        for row in conn.execute("PRAGMA table_info(session_relays)").fetchall()
    }
    assert relay_columns["actor_id"] is True
    assert relay_columns["hostname"] is True
    launch_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(session_launches)")
    }
    assert {
        "native_launch_pid",
        "native_launch_phase",
        "native_launch_observed_at",
        "spawn_duration_ms",
    } <= launch_columns


def test_closed_function_vocabulary_is_fully_registered() -> None:
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import (
        list_entries,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    register_all_handlers()

    registered = {entry.function_id for entry in list_entries()}
    assert set(SESSION_CONTROL_FUNCTION_IDS) <= registered


def test_portability_classifies_every_session_control_table() -> None:
    from yoke_core.domain.universe_portability_content_contract import (
        ARCHIVE_OMITTABLE_TARGET_TABLES,
        USER_CONTENT_TABLES,
    )

    portable = {"session_messages", "session_launches"}
    operational = set(required_tables()) - portable
    assert portable <= set(USER_CONTENT_TABLES)
    assert operational <= set(ARCHIVE_OMITTABLE_TARGET_TABLES)
    assert not (portable & set(ARCHIVE_OMITTABLE_TARGET_TABLES))
