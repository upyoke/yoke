"""Only the latest parent hook mode can establish Claude session posture."""

import json

import pytest

from yoke_harness.hooks import session_permission_mode as modes

SESSION = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(modes.machine_config, "cache_dir", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse"])
def test_hook_keeps_only_permission_mode(cache, event):
    modes.capture_permission_mode(
        {
            "session_id": SESSION,
            "hook_event_name": event,
            "permission_mode": "bypassPermissions",
            "prompt": "private prompt",
            "tool_input": {"command": "private command"},
        },
        "claude-code",
    )
    assert json.loads(next(cache.iterdir()).read_text()) == {
        "permission_mode": "bypassPermissions",
    }
    modes.capture_permission_mode(
        {"session_id": SESSION, "permission_mode": "default"}, "claude-code"
    )
    assert modes.read_permission_mode(SESSION) == {"permission_mode": "default"}


@pytest.mark.parametrize("extra", [{"agent_id": "child"}, {"agent_id": None}])
def test_subagent_cannot_overwrite_parent_mode(extra):
    modes.capture_permission_mode(
        {"session_id": SESSION, "permission_mode": "default"}, "claude-code"
    )
    modes.capture_permission_mode(
        {
            "session_id": SESSION,
            "permission_mode": "bypassPermissions",
            **extra,
        },
        "claude-code",
    )
    assert modes.read_permission_mode(SESSION) == {"permission_mode": "default"}


@pytest.mark.parametrize(
    "executor,payload",
    [
        ("codex", {"session_id": SESSION, "permission_mode": "bypassPermissions"}),
        ("claude-code", {"session_id": SESSION}),
        (
            "claude-code",
            {"session_id": "../invalid", "permission_mode": "bypassPermissions"},
        ),
    ],
)
def test_unrelated_or_invalid_payloads_are_not_recorded(cache, executor, payload):
    modes.capture_permission_mode(payload, executor)
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("contents", [None, "broken", "[]", "{}"])
def test_missing_or_unreadable_record_has_no_mode(cache, contents):
    if contents is not None:
        modes._cache_path(SESSION).write_text(contents)
    assert modes.read_permission_mode(SESSION) is None


def test_write_failure_invalidates_previous_mode(monkeypatch, capsys):
    modes.capture_permission_mode(
        {"session_id": SESSION, "permission_mode": "bypassPermissions"}, "claude-code"
    )
    monkeypatch.setattr(
        modes.os, "replace", lambda *a: (_ for _ in ()).throw(OSError())
    )
    modes.capture_permission_mode(
        {"session_id": SESSION, "permission_mode": "default"}, "claude-code"
    )
    assert modes.read_permission_mode(SESSION) is None
    assert capsys.readouterr().err.split(":", 1)[0] == "HARNESS_POSTURE_UNVERIFIED"


@pytest.mark.parametrize("route", ["local", "relay"])
def test_mode_is_recorded_before_hook_checks(monkeypatch, route):
    from yoke_harness.hooks import relay
    from yoke_cli.transport.https import HttpsConnection
    from yoke_contracts.hook_runner.project_scope import HookProjectScope

    monkeypatch.setattr(relay, "detect_executor", lambda: "claude-code")
    monkeypatch.setattr(relay, "lint_config_snapshot", lambda *a: {})
    monkeypatch.setattr(
        relay, "resolve_hook_project_scope", lambda *a: HookProjectScope(1)
    )
    monkeypatch.setattr(relay, "_record_client_anchor", lambda *a, **k: None)
    monkeypatch.setattr(relay, "_codex_capture", lambda *a: None)
    monkeypatch.setattr(relay, "stamp_hook_input", lambda *a: ("{}", None))
    monkeypatch.setattr(
        "yoke_harness.hooks.machine_hooks.ensure_machine_hooks_for_executor",
        lambda *a, **k: None,
    )

    class Checked(Exception):
        pass

    def check(*a, **k):
        assert modes.read_permission_mode(SESSION) == {"permission_mode": "default"}
        raise Checked()

    monkeypatch.setattr(relay, "evaluate_local_subset", check)
    payload = json.dumps({"session_id": SESSION, "permission_mode": "default"})
    with pytest.raises(Checked):
        if route == "local":
            relay.evaluate_hook_event("PreToolUse", stdin_data=payload)
        else:
            relay.relay_hook_event(
                "PreToolUse",
                HttpsConnection(api_url="https://example.test", token="test"),
                stdin_data=payload,
            )
