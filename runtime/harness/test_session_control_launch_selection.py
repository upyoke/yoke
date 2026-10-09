"""Launch preview/create send a level or one exact selection, never both."""

from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import session_control_launches as launches
from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result,
)


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


def test_a_level_reason_travels_with_an_item_level_create(monkeypatch) -> None:
    code, calls = _create(
        monkeypatch, "--level", "SENIOR", "--level-reason", " needs design judgment "
    )

    assert code == 0
    payload = calls[0]["payload"]
    assert payload["level"] == "SENIOR"
    assert payload["item"] == "YOK-2580"
    assert payload["level_reason"] == "needs design judgment"


def test_no_level_reason_is_sent_unless_stated(monkeypatch) -> None:
    code, calls = _create(monkeypatch, "--level", "SENIOR")

    assert code == 0
    assert "level_reason" not in calls[0]["payload"]


@pytest.mark.parametrize("selection", [(), ("--surface", "cursor-cli")])
def test_a_level_reason_without_a_level_is_refused_locally(
    monkeypatch, capsys, selection
) -> None:
    code, calls = _create(monkeypatch, *selection, "--level-reason", "why")

    assert code == 2
    assert calls == []
    assert _usage(capsys)["message"].startswith("level_reason_without_item_level")


def test_a_level_reason_without_an_item_is_refused_locally(monkeypatch, capsys) -> None:
    calls = _capture_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Itemless body."))

    code = launches.session_launch_create(
        [
            *("--project", "yoke", "--level", "SENIOR", "--level-reason", "why"),
            *("--raw-instructions", "--stdin", "--idempotency-key", "itemless"),
        ]
    )

    assert code == 2
    assert calls == []
    assert _usage(capsys)["message"].startswith("level_reason_without_item_level")


def test_a_level_reason_on_a_preview_is_refused_locally(monkeypatch, capsys) -> None:
    calls = _capture_dispatch(monkeypatch)

    code = launches.sessions_create(
        [
            *("--project", "yoke", "--level", "SENIOR", "--preview"),
            *("--item", "YOK-2580", "--level-reason", "why"),
        ]
    )

    assert code == 2
    assert calls == []
    assert _usage(capsys)["message"].startswith("level_reason_without_item_level")


def _created(payload: dict, result: dict) -> tuple[str, str]:
    out, err = io.StringIO(), io.StringIO()
    launches._create_result_writer(payload)(SimpleNamespace(result=result), out, err)
    return out.getvalue(), err.getvalue()


ITEM_LEVEL_CREATE = {"item": "YOK-1", "level": "SENIOR"}
RECORDED = {"level": "SENIOR", "reason": "why", "changed": True, "previous": None}


def test_a_server_that_echoes_the_item_level_needs_no_warning() -> None:
    _out, err = _created(
        ITEM_LEVEL_CREATE, {"deduplicated": False, "item_level": RECORDED}
    )

    assert err == ""


def test_a_server_predating_item_levels_is_named_with_the_manual_recipe() -> None:
    _out, err = _created(ITEM_LEVEL_CREATE, {"deduplicated": False})

    assert "item_level_unrecorded" in err
    assert "launch only" in err
    assert "yoke workflows item-posture amend YOK-1 --key level" in err
    assert '"min": "SENIOR"' in err


@pytest.mark.parametrize(
    ("payload", "result"),
    [
        (ITEM_LEVEL_CREATE, {"deduplicated": True}),
        ({"item": "YOK-1", "use_stage_level": True}, {"deduplicated": False}),
        ({"level": "SENIOR"}, {"deduplicated": False}),
    ],
    ids=["replay", "stage level", "itemless"],
)
def test_creates_that_record_no_item_level_need_no_warning(payload, result) -> None:
    _out, err = _created(payload, result)

    assert err == ""


def test_the_launch_receipt_names_the_item_level_it_recorded() -> None:
    out = io.StringIO()

    write_launch_result(
        {
            "launch": {"launch_id": "launch-1", "state": "assigned"},
            "deduplicated": False,
            "item_level": RECORDED,
        },
        out,
    )

    line = next(row for row in out.getvalue().splitlines() if "Item level" in row)
    assert "SENIOR for every stage, recorded (why)" in line


def test_the_launch_receipt_has_no_item_level_row_when_none_was_recorded() -> None:
    out = io.StringIO()

    write_launch_result(
        {
            "launch": {"launch_id": "launch-1", "state": "assigned"},
            "deduplicated": False,
            "item_level": None,
        },
        out,
    )

    assert "Item level" not in out.getvalue()
