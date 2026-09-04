"""Launch create leaves an unnamed model for the chosen machine to decide."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_launches as launches
from yoke_contracts.machine_config.preferred_session_models import (
    PREFERRED_SESSION_MODELS_KEY,
    PREFERRED_SESSION_REASONING_EFFORTS_KEY,
)


def _create(monkeypatch, *extra_args: str) -> dict:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(launches, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("start /yoke do"))
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: {
                "cursor-cli": "cursor-grok-4.6[context=1m]",
            },
            PREFERRED_SESSION_REASONING_EFFORTS_KEY: {"cursor-cli": "high"},
        },
    )

    assert (
        launches.session_launch_create(
            [
                "--project",
                "yoke",
                "--surface",
                "cursor-cli",
                "--stdin",
                "--item",
                "YOK-2580",
                "--idempotency-key",
                "launch-preferred",
                *extra_args,
            ]
        )
        == 0
    )
    assert calls[0]["function_id"] == "session_control.launch.create"
    return calls[0]["payload"]


def test_launch_create_without_model_leaves_the_machine_to_decide(
    monkeypatch,
) -> None:
    """This machine's map must not name a model for a session running elsewhere.

    The launch is placed on whichever machine has headroom, and that machine
    resolves its own default; filling it in here would send a model the target
    may not have installed.
    """
    payload = _create(monkeypatch)

    assert "model" not in payload


def test_an_explicit_selection_still_travels_with_the_launch(monkeypatch) -> None:
    payload = _create(
        monkeypatch,
        "--model",
        "cursor-grok-4.6",
        "--reasoning-effort",
        "high",
        "--context-window",
        "1m",
    )

    assert payload["model"] == "cursor-grok-4.6"
    assert payload["reasoning_effort"] == "high"
    assert payload["context_window_tokens"] == 1_000_000


def test_launch_create_list_models_names_source_without_dispatch(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(launches, "dispatch_and_emit", lambda **kwargs: 1)
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: {
                "claude-cli": "claude-opus-4-8[1m]",
            },
            PREFERRED_SESSION_REASONING_EFFORTS_KEY: {"claude-cli": "max"},
        },
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: tmp_path / "config.json",
    )

    assert (
        launches.session_launch_create(["--list-models", "--surface", "claude-cli"])
        == 0
    )
    rendered = capsys.readouterr().out
    assert PREFERRED_SESSION_MODELS_KEY in rendered
    assert "claude-opus-4-8" in rendered
    assert "documented CLI contract" in rendered
