"""Worktree remount fold: new conversation aliases claim-holder session."""

from __future__ import annotations

import json
import threading

from yoke_contracts.cursor_remount_expect import (
    REMOUNT_OBSERVING,
    REMOUNT_REFUSED,
    REMOUNT_REFUSAL_PAYLOAD_FIELD,
    consume_remount_expect,
    remount_expect_is_live,
    write_remount_expect,
)
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    linked_worktree_lane_name,
)
from yoke_core.hooks.cursor_worktree_session_fold import (
    resolve_worktree_remap_container,
)
from yoke_core.hooks.cursor_payload import parse_payload


CONTAINER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REMAPPED = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WORKTREE = "/repo/.worktrees/YOK-2026"


def test_linked_worktree_lane_name_yoke_layout() -> None:
    assert linked_worktree_lane_name("/repo/.worktrees/YOK-2026") == "YOK-2026"
    assert linked_worktree_lane_name("/repo/.worktrees/YOK-2026/packages") == "YOK-2026"
    assert linked_worktree_lane_name("/repo") == ""
    assert linked_worktree_lane_name("/repo/worktrees/YOK-2026") == ""
    assert linked_worktree_lane_name("/repo/.claude/worktrees/YOK-9") == "YOK-9"


def test_resolve_worktree_remap_container_uses_holder_lookup(tmp_path) -> None:
    write_remount_expect(tmp_path, CONTAINER, CONTAINER)
    payload = {
        "hook_event_name": "sessionStart",
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert (
        resolve_worktree_remap_container(
            payload,
            holder_lookup=lambda lane: CONTAINER if lane == "YOK-2026" else "",
            map_dir=tmp_path,
        )
        == CONTAINER
    )
    payload["hook_event_name"] = "beforeSubmitPrompt"
    assert (
        resolve_worktree_remap_container(
            payload,
            holder_lookup=lambda lane: CONTAINER if lane == "YOK-2026" else "",
            map_dir=tmp_path,
        )
        == CONTAINER
    )
    # Same id as holder → no fold (avoid self-alias noise).
    assert (
        resolve_worktree_remap_container(
            {"session_id": CONTAINER, "workspace_roots": [WORKTREE]},
            holder_lookup=lambda _lane: CONTAINER,
            map_dir=tmp_path,
        )
        == ""
    )


def test_resolve_worktree_remap_container_requires_live_expect(tmp_path) -> None:
    payload = {
        "session_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert (
        resolve_worktree_remap_container(
            payload,
            holder_lookup=lambda _lane: CONTAINER,
            map_dir=tmp_path,
        )
        == ""
    )


def test_parse_payload_folds_worktree_remap(monkeypatch) -> None:
    from yoke_core.hooks import cursor_worktree_session_fold as fold

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
    from yoke_core.hooks.cursor_worktree_session_fold import (
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
    from yoke_core.hooks.cursor_worktree_session_fold import (
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


def test_record_remount_writes_new_conversation_to_holder(tmp_path) -> None:
    from yoke_core.hooks.cursor_worktree_session_fold import (
        record_remount_conversation_session,
    )

    write_remount_expect(tmp_path, CONTAINER, CONTAINER)
    recorded = []
    payload = {
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert (
        record_remount_conversation_session(
            payload,
            holder_lookup=lambda _lane: CONTAINER,
            record=lambda conv, sid: recorded.append((conv, sid)),
            map_dir=tmp_path,
        )
        == ""
    )
    holder = record_remount_conversation_session(
        payload,
        holder_lookup=lambda _lane: CONTAINER,
        record=lambda conv, sid: recorded.append((conv, sid)),
        map_dir=tmp_path,
    )
    assert holder == CONTAINER
    assert recorded == [(REMAPPED, CONTAINER)]
    assert not remount_expect_is_live(tmp_path, CONTAINER)


def test_holder_hook_after_candidate_refuses_fold(tmp_path) -> None:
    write_remount_expect(tmp_path, CONTAINER, CONTAINER)
    payload = {
        "hook_event_name": "sessionStart",
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert (
        resolve_worktree_remap_container(
            payload,
            holder_lookup=lambda _lane: CONTAINER,
            map_dir=tmp_path,
        )
        == CONTAINER
    )

    write_remount_expect(tmp_path, CONTAINER, CONTAINER)
    payload["hook_event_name"] = "beforeSubmitPrompt"
    assert (
        resolve_worktree_remap_container(
            payload,
            holder_lookup=lambda _lane: CONTAINER,
            map_dir=tmp_path,
        )
        == ""
    )
    assert payload[REMOUNT_REFUSAL_PAYLOAD_FIELD]["holder_session_id"] == CONTAINER
    assert payload[REMOUNT_REFUSAL_PAYLOAD_FIELD]["lane"] == "YOK-2026"


def test_relay_evaluated_remount_continues_when_holder_stays_quiet(
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.hooks import cursor_worktree_session_fold as fold

    home = tmp_path / "home"
    map_dir = home / CURSOR_SESSION_MAP_DIR_NAME
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setattr(fold, "_holder_session_for_lane", lambda _lane: CONTAINER)
    write_remount_expect(map_dir, CONTAINER, CONTAINER)

    payload = {
        "hook_event_name": "sessionStart",
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert parse_payload(json.dumps(payload))["session_id"] == CONTAINER
    payload["hook_event_name"] = "beforeSubmitPrompt"
    assert parse_payload(json.dumps(payload))["session_id"] == CONTAINER
    payload["hook_event_name"] = "preToolUse"
    assert parse_payload(json.dumps(payload))["session_id"] == CONTAINER


def test_relay_evaluated_second_window_keeps_distinct_identity(
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.hooks import cursor_worktree_session_fold as fold

    home = tmp_path / "home"
    map_dir = home / CURSOR_SESSION_MAP_DIR_NAME
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setattr(fold, "_holder_session_for_lane", lambda _lane: CONTAINER)
    write_remount_expect(map_dir, CONTAINER, CONTAINER)
    payload = {
        "hook_event_name": "sessionStart",
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [WORKTREE],
    }
    assert parse_payload(json.dumps(payload))["session_id"] == CONTAINER

    write_remount_expect(map_dir, CONTAINER, CONTAINER)
    payload["hook_event_name"] = "beforeSubmitPrompt"
    refused = parse_payload(json.dumps(payload))
    assert refused["session_id"] == REMAPPED
    assert refused["identity_stamped"] is True
    assert refused[REMOUNT_REFUSAL_PAYLOAD_FIELD]["holder_session_id"] == CONTAINER


def test_record_remount_without_expect_writes_nothing(tmp_path) -> None:
    from yoke_core.hooks.cursor_worktree_session_fold import (
        record_remount_conversation_session,
    )

    recorded = []
    holder = record_remount_conversation_session(
        {
            "session_id": REMAPPED,
            "conversation_id": REMAPPED,
            "workspace_roots": [WORKTREE],
        },
        holder_lookup=lambda _lane: CONTAINER,
        record=lambda conv, sid: recorded.append((conv, sid)),
        map_dir=tmp_path,
    )
    assert holder == ""
    assert recorded == []


def test_remount_expect_write_consume_and_expiry(tmp_path, monkeypatch) -> None:
    assert write_remount_expect(tmp_path, CONTAINER)
    assert remount_expect_is_live(tmp_path, CONTAINER)
    assert consume_remount_expect(tmp_path, CONTAINER)
    assert not remount_expect_is_live(tmp_path, CONTAINER)
    assert not consume_remount_expect(tmp_path, CONTAINER)

    assert write_remount_expect(tmp_path, CONTAINER)
    monkeypatch.setenv("YOKE_HOOK_REPLAY", "1")
    assert not write_remount_expect(tmp_path, CONTAINER)
    assert remount_expect_is_live(tmp_path, CONTAINER)
    assert not consume_remount_expect(tmp_path, CONTAINER)
    monkeypatch.delenv("YOKE_HOOK_REPLAY", raising=False)
    assert consume_remount_expect(tmp_path, CONTAINER)


def test_candidate_and_holder_hook_mutations_are_serialized(
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_contracts import cursor_remount_expect as remount

    write_remount_expect(tmp_path, CONTAINER, CONTAINER)
    candidate_write_started = threading.Event()
    finish_candidate_write = threading.Event()
    original_write = remount._write_record

    def pause_candidate_write(path, record):
        if record.get("candidate_conversation_id") == REMAPPED:
            candidate_write_started.set()
            assert finish_candidate_write.wait(timeout=2)
        return original_write(path, record)

    monkeypatch.setattr(remount, "_write_record", pause_candidate_write)
    outcomes = {}
    candidate = threading.Thread(
        target=lambda: outcomes.setdefault(
            "candidate",
            remount.observe_remount_candidate(tmp_path, CONTAINER, REMAPPED),
        )
    )
    holder = threading.Thread(
        target=lambda: outcomes.setdefault(
            "holder",
            write_remount_expect(tmp_path, CONTAINER, CONTAINER),
        )
    )
    candidate.start()
    assert candidate_write_started.wait(timeout=2)
    holder.start()
    finish_candidate_write.set()
    candidate.join(timeout=2)
    holder.join(timeout=2)

    assert outcomes["candidate"].outcome == REMOUNT_OBSERVING
    assert outcomes["holder"] is True
    assert (
        remount.observe_remount_candidate(
            tmp_path,
            CONTAINER,
            REMAPPED,
        ).outcome
        == REMOUNT_REFUSED
    )
