"""Relay child environments cannot inherit the launching harness identity."""

from __future__ import annotations

import json

from yoke_contracts.session_identity import ACTOR_ROLE_ENV_VAR, AMBIENT_ENV_VARS
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_environment import native_session_environment


def test_native_environment_replaces_parent_identity_and_surface_facts() -> None:
    inherited = {
        "PATH": "/opt/native/bin",
        "YOKE_SESSION_ID": "parent-yoke-session",
        "CLAUDE_CODE_SESSION_ID": "parent-claude-session",
        "CODEX_SESSION_ID": "parent-codex-session",
        "CODEX_THREAD_ID": "parent-codex-thread",
        ACTOR_ROLE_ENV_VAR: "worker",
        "YOKE_EXECUTOR": "codex",
        "YOKE_EXECUTOR_VERSION": "parent-version",
        "YOKE_PROVIDER": "openai",
        "YOKE_MODEL": "parent-model",
        "CLAUDE_CODE_ENTRYPOINT": "desktop",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "codex-desktop",
        "CURSOR_INVOKED_AS": "cursor",
        "CURSOR_CONVERSATION_ID": "parent-cursor-session",
        "CURSOR_TRANSCRIPT_PATH": "/tmp/parent-transcript",
        "SHELL": "/bin/zsh",
        "BASH_ENV": "/tmp/parent-bash-env",
        "ENV": "/tmp/parent-sh-env",
        "ZDOTDIR": "/tmp/parent-zdotdir",
        LAUNCH_CONTEXT_ENV: '{"launch_id":"parent"}',
    }

    environment = native_session_environment(
        executor="claude-code",
        executor_version="2.1.238",
        provider="anthropic",
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
        launch_id="12345678-1234-4234-8234-123456789abc",
        launch_attestation="one-time-secret",
        environ=inherited,
    )

    assert environment["PATH"] == "/opt/native/bin"
    assert all(name not in environment for name in AMBIENT_ENV_VARS)
    assert ACTOR_ROLE_ENV_VAR not in environment
    assert environment["YOKE_EXECUTOR"] == "claude-code"
    assert environment["YOKE_EXECUTOR_VERSION"] == "2.1.238"
    assert environment["YOKE_PROVIDER"] == "anthropic"
    assert environment["SHELL"] == "/bin/sh"
    assert "BASH_ENV" not in environment
    assert "ENV" not in environment
    assert "ZDOTDIR" not in environment
    assert environment["CLAUDE_CODE_ENTRYPOINT"] == "cli"
    assert "YOKE_MODEL" not in environment
    assert "CODEX_INTERNAL_ORIGINATOR_OVERRIDE" not in environment
    assert "CURSOR_INVOKED_AS" not in environment
    assert "CURSOR_CONVERSATION_ID" not in environment
    assert "CURSOR_TRANSCRIPT_PATH" not in environment
    assert json.loads(environment[LAUNCH_CONTEXT_ENV]) == {
        "launch_id": "12345678-1234-4234-8234-123456789abc",
        "attestation": "one-time-secret",
    }


def test_native_environment_stamps_resolved_model_for_registration() -> None:
    environment = native_session_environment(
        executor="cursor",
        executor_version="2026.08.11-e8db854",
        provider="cursor",
        model="cursor-grok-4.6-high-fast",
        environ={"YOKE_MODEL": "parent-model"},
    )

    assert environment["YOKE_MODEL"] == "cursor-grok-4.6-high-fast"


def test_wake_environment_drops_stale_launch_context() -> None:
    environment = native_session_environment(
        executor="cursor",
        executor_version="2026.08.11-e8db854",
        environ={LAUNCH_CONTEXT_ENV: '{"launch_id":"stale"}'},
    )

    assert LAUNCH_CONTEXT_ENV not in environment
