"""Identity-enrichment tests for the HTTPS hook relay client.

``client_lane`` / ``client_model`` live in ``yoke_harness.hooks.identity_relay``
and surface through ``yoke_harness.hooks.identity``. Lane resolution reads
machine-config ``settings`` keys (``executor_default_lane_<token>``, with
``*`` wildcard suffixes and an ``unknown``/``primary`` default); model + codex
detection come from ``identity_relay``'s own module globals. Tests patch those
real surfaces.
"""

from __future__ import annotations

from yoke_harness.hooks.identity import client_lane, client_model

_RELAY = "yoke_harness.hooks.identity_relay"
_MACHINE_CONFIG = "yoke_cli.config.machine_config"


def test_client_lane_resolves_registration_events_from_machine_config(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        f"{_MACHINE_CONFIG}.load_config",
        lambda: {"settings": {"executor_default_lane_codex_desktop": "DARIUS"}},
    )

    assert client_lane("SessionStart", "codex-desktop") == "DARIUS"


def test_client_lane_skips_tool_call_events(monkeypatch) -> None:
    monkeypatch.setattr(
        f"{_RELAY}._routing_settings",
        lambda: (_ for _ in ()).throw(AssertionError("must not read settings")),
    )

    assert client_lane("PreToolUse", "codex-desktop") is None


def test_tool_call_client_model_marks_first_real_model_then_skips(
    monkeypatch, tmp_path,
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    monkeypatch.setattr(f"{_RELAY}.is_codex", lambda executor: False)
    monkeypatch.setattr(
        f"{_RELAY}.detect_model",
        lambda executor, transcript_path="":
            calls.append((executor, transcript_path)) or "claude-fable-5[1m]",
    )
    payload = {"session_id": "s-model", "transcript_path": "/t/live.jsonl"}

    assert client_model("PreToolUse", payload, "claude-code") == "claude-fable-5[1m]"
    assert client_model("PostToolUse", payload, "claude-code") is None
    assert calls == [("claude-code", "/t/live.jsonl")]
    assert (tmp_path / "relay-model-shipped" / "s-model").exists()


def test_placeholder_client_model_does_not_mark_shipped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    monkeypatch.setattr(f"{_RELAY}.is_codex", lambda executor: False)
    monkeypatch.setattr(
        f"{_RELAY}.detect_model",
        lambda executor, transcript_path="": "unknown",
    )

    assert client_model(
        "PreToolUse", {"session_id": "s-placeholder"}, "claude-code",
    ) is None
    assert not (tmp_path / "relay-model-shipped" / "s-placeholder").exists()


def test_client_project_id_resolves_workspace_roots_payloads(monkeypatch) -> None:
    """Cursor sessionStart payloads carry only ``workspace_roots`` (a list
    of absolute paths); the relay must resolve the project from it."""
    from yoke_harness.hooks.identity_relay import client_project_id

    monkeypatch.setattr(
        f"{_MACHINE_CONFIG}.project_id",
        lambda repo_root, path=None: 7 if str(repo_root) == "/checkouts/yoke" else None,
    )

    payload = {
        "hook_event_name": "sessionStart",
        "session_id": "s-roots",
        "workspace_roots": ["/checkouts/yoke"],
        "model": "composer-2.5",
    }
    assert client_project_id(payload) == 7


def test_client_project_id_scalar_keys_still_resolve(monkeypatch) -> None:
    from yoke_harness.hooks.identity_relay import client_project_id

    monkeypatch.setattr(
        f"{_MACHINE_CONFIG}.project_id",
        lambda repo_root, path=None: 3 if str(repo_root) == "/checkouts/app" else None,
    )

    assert client_project_id({"cwd": "/checkouts/app"}) == 3
    assert client_project_id({"workspace_roots": [], "cwd": ""}) is None
