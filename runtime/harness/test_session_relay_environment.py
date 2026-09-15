"""Relay child environments cannot inherit the launching harness identity."""

from __future__ import annotations

import json

from yoke_cli.config.session_relay_instance import RELAY_STATE_DIR_ENV
from yoke_contracts.session_identity import ACTOR_ROLE_ENV_VAR, AMBIENT_ENV_VARS
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_environment import (
    native_session_environment,
    strip_relay_owned_python_state,
)


RELAY_STATE_DIR = "/Users/example/.yoke/relay-instances/abcd1234"
RELAY_RELEASE = f"{RELAY_STATE_DIR}/releases/deadbeef"
RELAY_PYTHON_STATE = {
    RELAY_STATE_DIR_ENV: RELAY_STATE_DIR,
    "VIRTUAL_ENV": RELAY_RELEASE,
    "PYTHONPATH": f"{RELAY_RELEASE}/lib/python3.13/site-packages",
}


def test_native_environment_replaces_parent_identity_and_surface_facts() -> None:
    inherited = {
        "PATH": "/opt/native/bin",
        "YOKE_SESSION_ID": "parent-yoke-session",
        "CLAUDE_CODE_SESSION_ID": "parent-claude-session",
        "CODEX_SESSION_ID": "parent-codex-session",
        "CODEX_THREAD_ID": "parent-codex-thread",
        ACTOR_ROLE_ENV_VAR: "worker",
        "YOKE_EXECUTOR": "codex",
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


def test_a_foreign_binary_is_started_with_none_of_the_relay_python_state() -> None:
    environment = strip_relay_owned_python_state(
        {
            "PATH": (
                f"{RELAY_STATE_DIR}/venv/bin"
                f":{RELAY_STATE_DIR}/runtime/bin"
                ":/Users/example/.local/bin"
                ":/opt/homebrew/bin"
            ),
            "HOME": "/Users/example",
            **RELAY_PYTHON_STATE,
        }
    )

    assert "VIRTUAL_ENV" not in environment
    assert "PYTHONPATH" not in environment
    # The declaration goes too: a worker that could read it could write there.
    assert RELAY_STATE_DIR_ENV not in environment
    # Everything outside the relay's own tree is the user's, including the
    # directory the machine's installed `yoke` launcher lives in.
    assert environment["PATH"] == "/Users/example/.local/bin:/opt/homebrew/bin"
    assert environment["HOME"] == "/Users/example"


def test_a_search_path_the_relay_never_claimed_is_left_alone() -> None:
    environment = strip_relay_owned_python_state(
        {
            "PATH": "/Users/example/project/.venv/bin:/usr/bin",
            "VIRTUAL_ENV": "/Users/example/project/.venv",
        }
    )

    assert "VIRTUAL_ENV" not in environment
    assert environment["PATH"] == "/Users/example/project/.venv/bin:/usr/bin"


def test_the_relay_supervisor_keeps_the_state_its_own_imports_resolve_through() -> None:
    """The launcher process is not the boundary; stripping here breaks it.

    A supervisor and a detached worker both start on the stable runtime
    interpreter, which carries no packages of its own and reaches the
    selected release only through the variables below.
    """
    environment = native_session_environment(
        executor="codex",
        environ={"PATH": f"{RELAY_STATE_DIR}/venv/bin:/usr/bin", **RELAY_PYTHON_STATE},
    )

    assert environment["VIRTUAL_ENV"] == RELAY_PYTHON_STATE["VIRTUAL_ENV"]
    assert environment["PYTHONPATH"] == RELAY_PYTHON_STATE["PYTHONPATH"]
    assert environment["PATH"] == f"{RELAY_STATE_DIR}/venv/bin:/usr/bin"


def test_native_environment_stamps_resolved_model_for_registration() -> None:
    environment = native_session_environment(
        executor="cursor",
        provider="cursor",
        model="cursor-grok-4.6-high-fast",
        environ={"YOKE_MODEL": "parent-model"},
    )

    assert environment["YOKE_MODEL"] == "cursor-grok-4.6-high-fast"


def test_wake_environment_stamps_its_resume_attempt_after_the_parent_strip() -> None:
    from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV

    environment = native_session_environment(
        executor="cursor",
        resume_attempt_id="attempt-1",
        environ={RESUME_ATTEMPT_ENV: "stale-parent"},
    )

    assert environment[RESUME_ATTEMPT_ENV] == "attempt-1"


def test_create_environment_drops_an_inherited_resume_attempt() -> None:
    from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV

    environment = native_session_environment(
        executor="cursor",
        environ={RESUME_ATTEMPT_ENV: "stale-parent"},
    )

    assert RESUME_ATTEMPT_ENV not in environment


def test_wake_environment_drops_stale_launch_context() -> None:
    environment = native_session_environment(
        executor="cursor",
        environ={LAUNCH_CONTEXT_ENV: '{"launch_id":"stale"}'},
    )

    assert LAUNCH_CONTEXT_ENV not in environment
