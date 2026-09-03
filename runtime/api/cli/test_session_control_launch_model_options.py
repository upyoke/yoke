"""Launch CLI carries structured model knobs and teaches accepted values."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.commands.adapters import session_control_launches as launches


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


def test_list_models_names_documented_ids_and_effort_levels(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config", lambda path=None: {}
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.config_path",
        lambda: Path(tmp_path) / "config.json",
    )

    result = launches.session_launch_preview(
        ["--surface", "claude-cli", "--list-models"]
    )

    assert result == 0
    rendered = capsys.readouterr().out
    assert "claude-opus-4-8" in rendered
    assert "effort: low, medium, high, max" in rendered
    assert "context: 1m" in rendered
