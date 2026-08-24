"""Recipient selector, filter, authorization, and broadcast tests."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_service import preview_message
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


def test_typed_anchors_union_then_deduplicate_authoritative_claims() -> None:
    conn = message_connection()
    recipients = resolve_recipients(
        conn,
        selector(
            session_ids=["s1"],
            item_refs=["ALP-1"],
            epic_tasks=["ALP-1:1"],
            process_keys=["build-beta"],
        ),
        now=NOW,
    )

    assert [row.session_id for row in recipients] == ["s1", "s2", "s3"]
    assert recipients[0].resolution == ["session:s1", "item:ALP-1"]
    assert recipients[1].authorized_project_ids == {1}
    assert recipients[2].authorized_project_ids == {2}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"executor_families": ["cursor"]}, ["s3"]),
        ({"executor_surfaces": ["claude-cli"]}, ["s2"]),
        ({"work_roles": ["worker"]}, ["s2"]),
        ({"execution_lanes": ["direct"]}, ["s1", "s3", "s4"]),
        ({"worktree_lanes": ["alpha-worker"]}, ["s2"]),
        ({"machine_ids": ["m1"]}, ["s1"]),
    ],
)
def test_filters_intersect_after_anchor_union(
    filters: dict[str, list[str]], expected: list[str]
) -> None:
    conn = message_connection()
    recipients = resolve_recipients(
        conn,
        selector(projects=["alpha", "beta"], **filters),
        now=NOW,
    )
    assert [row.session_id for row in recipients] == expected


def test_exclusions_apply_after_union_without_retaining_duplicate_hits() -> None:
    conn = message_connection()
    recipients = resolve_recipients(
        conn,
        selector(
            session_ids=["s1", "s2"],
            item_refs=["ALP-1"],
            projects=["alpha"],
            exclude_session_ids=["s1"],
        ),
        now=NOW,
    )
    assert [row.session_id for row in recipients] == ["s2", "s4"]


def test_item_resolution_never_defaults_a_bare_reference_to_project() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError) as raised:
        resolve_recipients(conn, selector(item_refs=["1"]), now=NOW)
    assert raised.value.code == "target_not_found"


def test_unknown_project_never_defaults_to_alpha() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError, match="not found") as raised:
        resolve_recipients(conn, selector(projects=["unknown"]), now=NOW)
    assert raised.value.code == "target_not_found"


def test_zero_recipient_preview_is_an_explicit_outcome() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError) as raised:
        preview_message(
            conn,
            actor_id=10,
            selector=selector(session_ids=["not-a-session"]),
            now=NOW,
        )
    assert raised.value.code == "zero_recipients"


def test_cross_project_preview_authorizes_every_resolved_project() -> None:
    conn = message_connection()
    conn.execute("DELETE FROM actor_project_roles WHERE actor_id=10 AND project_id=2")
    conn.commit()
    with pytest.raises(SessionMessageError) as raised:
        preview_message(
            conn,
            actor_id=10,
            selector=selector(session_ids=["s1"], process_keys=["build-beta"]),
            now=NOW,
        )
    assert raised.value.code == "unauthorized_target"


def test_universe_preview_requires_org_admin_and_returns_exact_token() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError) as raised:
        preview_message(conn, actor_id=10, selector=selector(universe=True), now=NOW)
    assert raised.value.code == "unauthorized_broadcast"

    preview = preview_message(
        conn, actor_id=12, selector=selector(universe=True), now=NOW
    )
    assert preview["recipient_count"] == 4
    assert len(preview["confirmation_token"]) == 64


def test_version_qualified_messageability_fails_closed() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor_version='0.1.0' WHERE session_id='s1'"
    )
    recipient = resolve_recipients(conn, selector(session_ids=["s1"]), now=NOW)[0]
    assert recipient.messageability == {
        "messageable": False,
        "hook_injection": False,
        "wake_interface": "none",
        "wake_operation": "message_active",
        "reason": "version_below_floor_or_unknown",
        "minimum_version": "26.814.41407",
    }


def test_cursor_hashed_build_remains_hook_messageable() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor_version='2026.08.11-e8db854' "
        "WHERE session_id='s3'"
    )

    recipient = resolve_recipients(conn, selector(session_ids=["s3"]), now=NOW)[0]

    assert recipient.messageability["messageable"] is True
    assert recipient.messageability["hook_injection"] is True
