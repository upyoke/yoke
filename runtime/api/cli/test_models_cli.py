"""CLI request shape for the sourced model-reference adapters."""

from __future__ import annotations

import io
import json
import sys

from yoke_cli.commands.adapters import models


def test_lookup_dispatches_the_launch_model_string(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        models, "dispatch_and_emit", lambda **kwargs: captured.update(kwargs) or 0
    )

    assert models.models_lookup(["cursor-grok-4.6-high"]) == 0
    assert captured["function_id"] == "models.lookup.run"
    assert captured["payload"] == {"model_id": "cursor-grok-4.6-high"}
    assert captured["target"].kind == "global"


def test_get_without_model_id_sends_an_empty_payload(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        models, "dispatch_and_emit", lambda **kwargs: captured.update(kwargs) or 0
    )

    assert models.models_get([]) == 0
    assert captured["function_id"] == "models.get.run"
    assert captured["payload"] == {}


def test_validate_reads_one_json_object_from_stdin(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        models, "dispatch_and_emit", lambda **kwargs: captured.update(kwargs) or 0
    )
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"model_id": "x", "provider": "y"}))
    )

    assert models.models_validate(["--stdin"]) == 0
    assert captured["function_id"] == "models.validate.run"
    assert captured["payload"] == {"record": {"model_id": "x", "provider": "y"}}


def test_validate_without_stdin_is_a_usage_error() -> None:
    assert models.models_validate([]) == 2


def test_lookup_human_line_marks_unresearched() -> None:
    response = type(
        "Response",
        (),
        {"success": True, "result": {"model_id": "missing", "researched": False, "record": None}},
    )()
    output = io.StringIO()
    models._print_lookup(response, output, io.StringIO())
    assert "researched=false" in output.getvalue()
