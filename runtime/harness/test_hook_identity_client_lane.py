"""Identity-enrichment tests for the HTTPS hook relay client.

``client_lane`` lives in ``yoke_harness.hooks.identity_relay`` and the
model-facts half in ``yoke_harness.hooks.identity_model_facts``; both
surface through ``yoke_harness.hooks.identity``. Lane resolution reads
machine-config ``settings`` keys (``executor_default_lane_<token>``, with
``*`` wildcard suffixes and an ``unknown`` default), and answers ``None``
when nothing matches so the server's project routing policy decides. Model
facts split into the ask and whatever the harness artifact attested, so the
tests supply real artifacts rather than patching a single detector.
"""

from __future__ import annotations

import json

from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_harness.hooks.identity import (
    client_entrypoint,
    client_lane,
    client_model_facts,
    record_model_facts_shipped,
)

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
        f"{_MACHINE_CONFIG}.load_config",
        lambda: {"settings": {}},
    )

    assert client_lane("SessionStart", "claude-desktop") is None
    assert client_lane("UserPromptSubmit", "codex-desktop") is None


def test_client_lane_skips_tool_call_events(monkeypatch) -> None:
    monkeypatch.setattr(
        f"{_RELAY}._routing_settings",
        lambda: (_ for _ in ()).throw(AssertionError("must not read settings")),
    )

    assert client_lane("PreToolUse", "codex-desktop") is None


def _claude_transcript(tmp_path, model: str) -> str:
    path = tmp_path / "live.jsonl"
    path.write_text(
        json.dumps({"type": "assistant", "effort": "high", "message": {"model": model}})
        + "\n"
    )
    return str(path)


def test_an_attested_model_stops_resolving_once_its_write_lands(
    monkeypatch,
    tmp_path,
) -> None:
    """Reading the artifact is not free, so a RECORDED answer ends the work.

    Reading it is not the same as recording it: the hook carrying these
    facts still has to reach the control plane, so the session keeps
    reporting them until a caller says one landed.
    """
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    payload = {
        "session_id": "s-model",
        "transcript_path": _claude_transcript(tmp_path, "claude-fable-5"),
    }

    first = client_model_facts("PreToolUse", payload, "claude-code")

    assert first["model"] == "claude-fable-5"
    assert first["reasoning_effort"] == "high"
    assert not (tmp_path / "relay-model-shipped" / "s-model").exists()
    unsent = client_model_facts("PostToolUse", payload, "claude-code")
    assert unsent["model"] == "claude-fable-5"

    record_model_facts_shipped(payload, first["model"])

    assert (tmp_path / "relay-model-shipped" / "s-model").exists()
    assert client_model_facts("PostToolUse", payload, "claude-code") == {}


def test_an_unattested_session_ships_its_ask_and_keeps_trying(
    monkeypatch,
    tmp_path,
) -> None:
    """The artifact naming the served model does not exist on turn one."""
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    monkeypatch.setenv("YOKE_MODEL", "claude-opus-5[1m]")
    payload = {"session_id": "s-young", "transcript_path": str(tmp_path / "absent")}

    facts = client_model_facts("PreToolUse", payload, "claude-code")

    assert facts["requested_model"] == "claude-opus-5[1m]"
    assert "model" not in facts
    assert not (tmp_path / "relay-model-shipped" / "s-young").exists()


def test_cursor_attests_nothing_until_its_conversation_store_answers(
    monkeypatch, tmp_path
) -> None:
    # Cursor's payload names a family id before its conversation store names
    # the variant. That payload is not a measurement, so nothing is attested
    # and the client keeps trying until the store answers.
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    monkeypatch.setattr(
        "yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", tmp_path / "no-chats"
    )
    payload = {"session_id": "s-cursor", "model": "grok-4.6"}

    assert "model" not in client_model_facts("PreToolUse", payload, "cursor")
    assert not (tmp_path / "relay-model-shipped" / "s-cursor").exists()


def test_cursor_ships_the_variant_its_store_proves(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(f"{_MACHINE_CONFIG}.yoke_home", lambda: tmp_path)
    monkeypatch.setattr(
        "yoke_harness.model_attestation._cursor_facts",
        lambda _payload: SessionModelFacts(
            model="cursor-grok-4.6-xhigh", reasoning_effort="xhigh"
        ),
    )
    payload = {"session_id": "s-cursor-measured", "model": "grok-4.6"}

    facts = client_model_facts("PreToolUse", payload, "cursor")

    assert facts["model"] == "cursor-grok-4.6-xhigh"
    assert facts["reasoning_effort"] == "xhigh"


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
    assert client_entrypoint("claude-code", {"entrypoint": "cli"}) == "cli"

    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT")
    assert client_entrypoint("claude-code", {}) is None
