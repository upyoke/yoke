"""Launch preview/create send a level or one exact selection, never both."""

from __future__ import annotations

import io
import json
import sys

import pytest

from yoke_cli.commands.adapters import session_control_launches as launches


def _capture_dispatch(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(launches, "dispatch_and_emit", _dispatch)
    return calls


def _create(monkeypatch, *selection: str) -> tuple[int, list[dict]]:
    calls = _capture_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("start /yoke charge"))
    code = launches.session_launch_create(
        [
            "--project",
            "yoke",
            *selection,
            "--stdin",
            "--item",
            "YOK-2580",
            "--idempotency-key",
            "launch-selection",
        ]
    )
    return code, calls


def _usage(capsys) -> dict:
    return json.loads(capsys.readouterr().err.strip().splitlines()[-1])


def test_create_without_selector_requests_the_live_stage_default(monkeypatch):
    code, calls = _create(monkeypatch)
    assert code == 0
    assert calls[0]["payload"]["use_stage_level"] is True
    assert "level" not in calls[0]["payload"]
    assert "executor_surface" not in calls[0]["payload"]


def test_a_surface_launch_without_model_leaves_the_vendor_default(
    monkeypatch,
) -> None:
    code, calls = _create(monkeypatch, "--surface", "cursor-cli")

    assert code == 0
    assert calls[0]["function_id"] == "session_control.launch.create"
    payload = calls[0]["payload"]
    assert payload["executor_surface"] == "cursor-cli"
    assert "model" not in payload
    assert "level" not in payload


def test_an_explicit_selection_travels_with_the_launch(monkeypatch) -> None:
    code, calls = _create(
        monkeypatch,
        "--surface",
        "cursor-cli",
        "--model",
        "cursor-grok-4.6",
        "--reasoning-effort",
        "high",
        "--context-window",
        "1m",
    )

    assert code == 0
    payload = calls[0]["payload"]
    assert payload["model"] == "cursor-grok-4.6"
    assert payload["reasoning_effort"] == "high"
    assert payload["context_window_tokens"] == 1_000_000


def test_a_level_launch_sends_only_the_level(monkeypatch) -> None:
    code, calls = _create(monkeypatch, "--level", "senior", "--machine", "studio")

    assert code == 0
    payload = calls[0]["payload"]
    assert payload["level"] == "senior"
    assert payload["machine_id"] == "studio"
    for field in (
        "executor_surface",
        "model",
        "reasoning_effort",
        "context_window_tokens",
        "allow_surface_fallback",
    ):
        assert field not in payload
    assert payload["idempotency_key"] == "launch-selection"


def test_a_level_preview_dispatches_the_preview_function(monkeypatch) -> None:
    calls = _capture_dispatch(monkeypatch)

    assert (
        launches.session_launch_preview(["--project", "yoke", "--level", "JUNIOR"]) == 0
    )
    assert calls[0]["function_id"] == "session_control.launch.preview"
    assert calls[0]["payload"] == {"project": "yoke", "level": "JUNIOR"}


def test_sessions_create_preview_accepts_a_level(monkeypatch) -> None:
    calls = _capture_dispatch(monkeypatch)

    assert (
        launches.sessions_create(
            ["--project", "yoke", "--level", "SENIOR", "--preview"]
        )
        == 0
    )
    assert calls[0]["function_id"] == "session_control.launch.preview"
    assert calls[0]["payload"]["level"] == "SENIOR"


@pytest.mark.parametrize(
    ("extra", "flag"),
    [
        (["--surface", "claude-cli"], "--surface"),
        (["--model", "claude-opus-5-5"], "--model"),
        (["--reasoning-effort", "high"], "--reasoning-effort"),
        (["--context-window", "1m"], "--context-window"),
        (["--allow-surface-fallback"], "--allow-surface-fallback"),
    ],
)
def test_a_level_with_any_exact_knob_is_refused_locally(
    monkeypatch, capsys, extra, flag
) -> None:
    code, calls = _create(monkeypatch, "--level", "SENIOR", *extra)

    assert code == 2
    assert calls == []
    refusal = _usage(capsys)
    assert refusal["message"].startswith("level_selection_conflict")
    assert flag in refusal["message"]


def test_a_preview_naming_neither_is_refused(monkeypatch, capsys) -> None:
    calls = _capture_dispatch(monkeypatch)

    assert launches.session_launch_preview(["--project", "yoke"]) == 2
    assert calls == []
    assert _usage(capsys)["message"].startswith("launch_selection_missing")


def test_list_models_reports_accepted_flags_without_dispatch(
    monkeypatch, capsys
) -> None:
    calls = _capture_dispatch(monkeypatch)
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_models.observe_native_models",
        lambda *args, **kwargs: {},
    )

    assert (
        launches.session_launch_create(["--list-models", "--surface", "claude-cli"])
        == 0
    )
    assert calls == []
    rendered = capsys.readouterr().out
    assert "chosen by level options" in rendered
    assert "claude-cli accepted by the CLI flags:" in rendered
    assert "context: 1m" in rendered
    assert "claude-cli available (unknown, not observed)" in rendered
