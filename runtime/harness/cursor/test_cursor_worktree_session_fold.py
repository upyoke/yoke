"""Worktree remount fold: new conversation aliases claim-holder session."""

from __future__ import annotations

from yoke_contracts.cursor_session_map import linked_worktree_lane_name
from runtime.harness.cursor.cursor_worktree_session_fold import (
    resolve_worktree_remap_container,
)
from runtime.harness.cursor.cursor_hooks_payload import parse_payload


CONTAINER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REMAPPED = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_linked_worktree_lane_name_yoke_layout() -> None:
    assert (
        linked_worktree_lane_name("/repo/.worktrees/YOK-2026") == "YOK-2026"
    )
    assert (
        linked_worktree_lane_name("/repo/.worktrees/YOK-2026/packages")
        == "YOK-2026"
    )
    assert linked_worktree_lane_name("/repo") == ""
    assert linked_worktree_lane_name("/repo/worktrees/YOK-2026") == ""
    assert (
        linked_worktree_lane_name("/repo/.claude/worktrees/YOK-9") == "YOK-9"
    )


def test_resolve_worktree_remap_container_uses_holder_lookup() -> None:
    payload = {
        "session_id": REMAPPED,
        "workspace_roots": ["/repo/.worktrees/YOK-2026"],
    }
    assert (
        resolve_worktree_remap_container(
            payload, holder_lookup=lambda lane: CONTAINER if lane == "YOK-2026" else "",
        )
        == CONTAINER
    )
    # Same id as holder → no fold (avoid self-alias noise).
    assert (
        resolve_worktree_remap_container(
            {"session_id": CONTAINER, "workspace_roots": ["/repo/.worktrees/YOK-2026"]},
            holder_lookup=lambda _lane: CONTAINER,
        )
        == ""
    )


def test_parse_payload_folds_worktree_remap(monkeypatch) -> None:
    from runtime.harness.cursor import cursor_worktree_session_fold as fold

    monkeypatch.setattr(
        fold,
        "resolve_worktree_remap_container",
        lambda _data, **_kw: CONTAINER,
    )
    data = parse_payload(
        "{"
        f'"session_id": "{REMAPPED}", '
        f'"conversation_id": "{REMAPPED}", '
        '"workspace_roots": ["/repo/.worktrees/YOK-2026"]'
        "}"
    )
    assert data["session_id"] == CONTAINER
    assert data["container_session_id"] == CONTAINER
    assert data["is_worktree_remap_session"] is True
    assert data["is_subagent_session"] is False
    assert data["remapped_conversation_id"] == REMAPPED


def test_record_remount_writes_self_map() -> None:
    from runtime.harness.cursor.cursor_worktree_session_fold import (
        record_remount_conversation_session,
    )

    recorded = []
    holder = record_remount_conversation_session(
        {
            "session_id": CONTAINER,
            "conversation_id": CONTAINER,
            "workspace_roots": ["/repo/.worktrees/YOK-2026"],
        },
        holder_lookup=lambda _lane: CONTAINER,
        record=lambda conv, sid: recorded.append((conv, sid)),
    )
    assert holder == CONTAINER
    assert recorded == [(CONTAINER, CONTAINER)]


def test_record_remount_absent_holder_writes_nothing() -> None:
    from runtime.harness.cursor.cursor_worktree_session_fold import (
        record_remount_conversation_session,
    )

    recorded = []
    holder = record_remount_conversation_session(
        {
            "session_id": REMAPPED,
            "conversation_id": REMAPPED,
            "workspace_roots": ["/repo/.worktrees/YOK-2026"],
        },
        holder_lookup=lambda _lane: "",
        record=lambda conv, sid: recorded.append((conv, sid)),
    )
    assert holder == ""
    assert recorded == []


def test_record_remount_writes_new_conversation_to_holder() -> None:
    from runtime.harness.cursor.cursor_worktree_session_fold import (
        record_remount_conversation_session,
    )

    recorded = []
    holder = record_remount_conversation_session(
        {
            "session_id": REMAPPED,
            "conversation_id": REMAPPED,
            "workspace_roots": ["/repo/.worktrees/YOK-2026"],
        },
        holder_lookup=lambda _lane: CONTAINER,
        record=lambda conv, sid: recorded.append((conv, sid)),
    )
    assert holder == CONTAINER
    assert recorded == [(REMAPPED, CONTAINER)]
