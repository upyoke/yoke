"""CLI request shape for the sourced model-reference adapters."""

from __future__ import annotations

import io
import json
import sys

from yoke_cli.commands.adapters import models, models_level_proposal


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
        {
            "success": True,
            "result": {"model_id": "missing", "researched": False, "record": None},
        },
    )()
    output = io.StringIO()
    models._print_lookup(response, output, io.StringIO())
    assert "researched=false" in output.getvalue()


def test_level_proposal_sends_authored_changes_from_stdin(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        models_level_proposal,
        "dispatch_and_emit",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    changes = [{"kind": "retire", "option": {"surface": "codex-cli"}}]
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(changes)))

    assert models_level_proposal.models_level_proposal(["--stdin"]) == 0
    assert captured["function_id"] == "models.level_proposal.run"
    assert captured["payload"] == {"changes": changes}
    assert models_level_proposal.models_level_proposal(["--levels-only", "--json"]) == 2


def test_level_proposal_levels_only_prints_the_approval_document() -> None:
    levels = [{"name": "ONLY", "glyph": "x", "options": []}]
    response = type("Response", (), {"success": True, "result": {"levels": levels}})()
    output = io.StringIO()
    models_level_proposal._print_levels_only(response, output, io.StringIO())
    assert json.loads(output.getvalue()) == {"levels": levels}


def test_level_proposal_human_output_names_each_change_and_the_approval() -> None:
    option = {"surface": "claude-cli", "model": "m", "reasoning_effort": "high"}
    result = {
        "revision_id": "rev",
        "base_source": "universe",
        "generated": True,
        "changes": [
            {"kind": "retire", "option": option, "reason": "superseded"},
            {"kind": "add", "level": "SENIOR", "position": 0, "option": option},
            {"kind": "change", "option": option, "reasoning_effort": "low"},
        ],
        "unverified": [
            {
                "level": "SENIOR",
                "surface": "claude-cli",
                "model": "m",
                "reason": "model not in catalog",
            }
        ],
        "unplaced_models": [{"model_id": "new", "provider": "p"}],
        "apply_command": "yoke universe levels set --stdin",
    }
    response = type("Response", (), {"success": True, "result": result})()
    output = io.StringIO()
    models_level_proposal._print_level_proposal(response, output, io.StringIO())
    text = output.getvalue()
    assert "retire claude-cli m effort=high" in text
    assert "to SENIOR at 0" in text
    assert "-> reasoning_effort=low" in text
    assert "unplaced: new" in text
    assert "yoke universe levels set --stdin" in text
