"""Identity-enrichment tests for the HTTPS hook relay client.

``client_lane`` / ``client_model`` live in ``yoke_harness.hooks.identity_relay``
and surface through ``yoke_harness.hooks.identity``. Lane resolution reads
machine-config ``settings`` keys (``executor_default_lane_<token>``, with
``*`` wildcard suffixes and an ``unknown`` default), and answers ``None``
when nothing matches so the server's project routing policy decides; model +
codex detection come from ``identity_relay``'s own module globals. Tests
patch those real surfaces.
"""

from __future__ import annotations

from yoke_harness.hooks.identity import client_entrypoint, client_lane, client_model

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


def test_client_lane_without_machine_config_match_is_none(monkeypatch) -> None:
    """No local match must not invent a lane for the wire.

    Routing policy normally lives in the project's session-routing
    capability, which the client cannot read, so a placeholder shipped from
    here would arrive server-side as an explicit lane and overrule it.
    """
    monkeypatch.setattr(
        f"{_MACHINE_CONFIG}.load_config", lambda: {"settings": {}},
    )

    assert client_lane("SessionStart", "claude-desktop") is None
    assert client_lane("UserPromptSubmit", "codex-desktop") is None


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


def test_client_entrypoint_resolves_cursor_surface_from_executor(monkeypatch) -> None:
    """Cursor's surface comes from the executor family, not ambient transcript env.

    On an https machine the client-side register self-skips, so this is the
    only entrypoint that reaches the server. The rendered Cursor hook
    command pins the family, and the IDE surface has not exported
    ``CURSOR_TRANSCRIPT_PATH`` yet at sessionStart — so an env-only
    resolution would answer ``None`` and leave the alias unrecorded.
    """
    for var in (
        "CLAUDE_CODE_ENTRYPOINT",
        "CODEX_THREAD_ID",
        "CURSOR_INVOKED_AS",
        "CURSOR_TRANSCRIPT_PATH",
    ):
        monkeypatch.delenv(var, raising=False)

    assert client_entrypoint("cursor", {"session_id": "s-1"}) == "cursor-desktop"

    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    assert client_entrypoint("cursor", {"session_id": "s-1"}) == "cursor-cli"


def test_client_entrypoint_non_cursor_families_unchanged(monkeypatch) -> None:
    for var in ("CODEX_THREAD_ID", "CURSOR_INVOKED_AS", "CURSOR_TRANSCRIPT_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")

    assert client_entrypoint("claude-code", {}) == "claude-desktop"

    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    assert client_entrypoint("claude-code", {}) is None
