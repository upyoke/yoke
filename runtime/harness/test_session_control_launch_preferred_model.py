"""Launch create consults the machine-local preferred-model map."""

from __future__ import annotations

import io
import sys

from yoke_cli.commands.adapters import session_control_launches as launches
from yoke_contracts.machine_config.preferred_session_models import (
    PREFERRED_SESSION_MODELS_KEY,
)


def test_launch_create_without_model_sends_configured_preference(
    monkeypatch,
) -> None:
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
                "cursor-cli": "cursor-grok-4.6-high-fast",
            }
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
                "--idempotency-key",
                "launch-preferred",
            ]
        )
        == 0
    )
    assert calls[0]["function_id"] == "session_control.launch.create"
    assert calls[0]["payload"]["model"] == "cursor-grok-4.6-high-fast"


def test_launch_create_list_models_names_source_without_dispatch(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(launches, "dispatch_and_emit", lambda **kwargs: 1)
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config",
        lambda path=None: {
            PREFERRED_SESSION_MODELS_KEY: {"cursor-cli": "preferred-model"}
        },
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: tmp_path / "config.json",
    )

    assert (
        launches.session_launch_create(["--list-models", "--surface", "cursor-cli"])
        == 0
    )
    rendered = capsys.readouterr().out
    assert PREFERRED_SESSION_MODELS_KEY in rendered
    assert "preferred-model" in rendered
    assert "source:" in rendered
