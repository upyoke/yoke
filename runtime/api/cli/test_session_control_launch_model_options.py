"""Launch CLI carries structured model knobs and teaches accepted values."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.commands.adapters import session_control_launches as launches
from yoke_contracts.session_control.native_models import (
    NO_ADAPTER_REASON,
    empty_reading,
    models_reading,
    native_model,
)


def test_claude_create_parses_and_dispatches_every_model_knob(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        launches,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    result = launches.session_launch_create(
        [
            "--project",
            "yoke",
            "--surface",
            "claude-cli",
            "--model",
            "claude-opus-4-8",
            "--reasoning-effort",
            "max",
            "--context-window",
            "1m",
            "--item",
            "YOK-1",
            "--idempotency-key",
            "model-selection",
        ]
    )

    assert result == 0
    assert calls[0]["payload"]["model"] == "claude-opus-4-8"
    assert calls[0]["payload"]["reasoning_effort"] == "max"
    assert calls[0]["payload"]["context_window_tokens"] == 1_000_000


def test_unsupported_cli_combination_prints_named_recovery(capsys) -> None:
    result = launches.session_launch_preview(
        [
            "--project",
            "yoke",
            "--surface",
            "codex-cli",
            "--model",
            "gpt-5.6-sol",
            "--context-window",
            "1m",
        ]
    )

    assert result == 2
    assert "codex_context_window_unsupported" in capsys.readouterr().err


def test_list_models_separates_flag_grammar_from_observed_availability(
    monkeypatch, capsys, tmp_path
) -> None:
    # What the flags accept is the same on every machine and stays declared.
    # Which models the account can select is observed, so a surface nobody has
    # listed says so instead of quoting a compiled-in catalog.
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config", lambda path=None: {}
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: Path(tmp_path) / "config.json",
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_models.observe_native_models",
        lambda **_kwargs: {
            "claude-cli": empty_reading("claude-cli", "unsupported", NO_ADAPTER_REASON)
        },
    )

    result = launches.session_launch_preview(
        ["--surface", "claude-cli", "--list-models"]
    )

    assert result == 0
    rendered = capsys.readouterr().out
    assert "effort: low, medium, high, max" in rendered
    assert "context: 1m" in rendered
    assert NO_ADAPTER_REASON in rendered


def test_list_models_names_the_models_a_surface_actually_published(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config", lambda path=None: {}
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: Path(tmp_path) / "config.json",
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_models.observe_native_models",
        lambda **_kwargs: {
            "codex-cli": models_reading(
                "codex-cli",
                [native_model("gpt-6-astra")],
                source="codex app-server model/list",
                observed_at="2026-09-07T14:00:00Z",
            )
        },
    )

    result = launches.session_launch_preview(
        ["--surface", "codex-cli", "--list-models"]
    )

    assert result == 0
    rendered = capsys.readouterr().out
    assert "codex-cli available (ok, codex app-server model/list)" in rendered
    assert "models: gpt-6-astra" in rendered
    assert "observed 2026-09-07T14:00:00Z" in rendered
