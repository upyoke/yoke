"""Client-folded Cursor identity across the HTTPS hook relay."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lint_session_cwd_identity import (
    FAILURE_CLASS as IDENTITY_FAILURE_CLASS,
)
from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS
from yoke_harness.hooks import cursor_lifecycle_hooks, relay
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


HOLDER = "sid-cursor-holder"
CONVERSATION = "conv-cursor-remount"
ITEM_ID = 4102


@pytest.fixture()
def relay_capture(monkeypatch):
    captured = {}
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay, "detect_executor", lambda: "cursor")
    monkeypatch.setattr(relay, "_client_lint_config_snapshot", lambda _payload: {})
    monkeypatch.setattr(relay, "_record_client_anchor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        relay,
        "relay_identity_payload",
        lambda *_args: {
            "entrypoint": "cursor",
            "model": None,
            "execution_lane": None,
            "project_id": 1,
        },
    )
    monkeypatch.setattr(
        relay,
        "evaluate_local_subset",
        lambda *_args, **_kwargs: LocalSubsetEvaluation(
            stdout="", exit_code=0, denied=False,
        ),
    )
    monkeypatch.setattr(
        cursor_lifecycle_hooks,
        "ensure_user_lifecycle_hooks_for_executor",
        lambda _executor: None,
    )

    def request_json(request, **_kwargs):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return SimpleNamespace(payload={
            "stdout": "", "exit_code": 0, "outcome": "completed",
        })

    monkeypatch.setattr(relay, "request_json", request_json)
    return captured


def _held_lane(conn, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees").mkdir(parents=True)
    seed_item(conn, item_id=ITEM_ID, branch="held-lane", repo_path=repo)
    seed_item_claim(conn, HOLDER, item_id=ITEM_ID)
    lane = repo / ".worktrees" / "held-lane"
    lane.mkdir(parents=True)
    return lane


def _cursor_write(lane):
    return {
        "session_id": CONVERSATION,
        "conversation_id": CONVERSATION,
        "tool_name": "Write",
        "tool_input": {"file_path": str(lane / "source.py")},
    }


def _relay_payload(payload, relay_capture):
    connection = HttpsConnection(api_url="https://env.example", token="token")
    assert relay.relay_hook_event(
        "PreToolUse", connection, stdin_data=json.dumps(payload),
    ) == 0
    return json.loads(relay_capture["body"]["stdin"])


def test_mapped_cursor_identity_reaches_raw_matching_server(
    tmp_path, monkeypatch, relay_capture,
) -> None:
    local_home = tmp_path / "local-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(local_home))
    record_conversation_session(
        CONVERSATION,
        HOLDER,
        local_home / CURSOR_SESSION_MAP_DIR_NAME,
    )

    with test_database() as conn:
        lane = _held_lane(conn, tmp_path)
        relayed = _relay_payload(_cursor_write(lane), relay_capture)
        assert relayed["session_id"] == HOLDER

        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "server-home"))
        verdict = lint_session_cwd.evaluate_pre_tool_use(relayed)
        assert verdict.allow is True
        assert verdict.session_id == HOLDER


def test_unmapped_cursor_identity_reaches_server_empty_and_denies_lane_write(
    tmp_path, monkeypatch, relay_capture,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "local-home"))

    with test_database() as conn:
        lane = _held_lane(conn, tmp_path)
        relayed = _relay_payload(_cursor_write(lane), relay_capture)
        assert relayed["session_id"] == ""

        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "server-home"))
        verdict = lint_session_cwd.evaluate_pre_tool_use(relayed)
        assert verdict.allow is False
        assert verdict.failure_class == IDENTITY_FAILURE_CLASS
