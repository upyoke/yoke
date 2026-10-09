"""CLI rendering of the operator execution-instruction block."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import workflow_execution_instructions as adapters
from yoke_cli.commands.adapters.workflow_execution_instructions import (
    EXECUTION_INSTRUCTION_BLOCK_HEADER,
    USAGE_BY_FUNCTION_ID,
    render_execution_instruction_block,
)
from yoke_cli.commands.registry_workflow_execution_instructions import (
    EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY,
)


def test_empty_match_set_renders_no_block() -> None:
    assert render_execution_instruction_block([]) == ""


def test_the_block_is_the_prose_under_one_header() -> None:
    """No per-instruction subheader: the prose is the whole instruction, and a
    title would have been a second summary the agent had to reconcile."""
    block = render_execution_instruction_block(
        [
            {"content": "Always run doctor.\n"},
            {"content": "QA gate is mandatory."},
        ]
    )

    lines = block.splitlines()
    assert lines[0] == EXECUTION_INSTRUCTION_BLOCK_HEADER
    assert "Always run doctor." in lines
    assert "QA gate is mandatory." in lines
    assert not [line for line in lines[1:] if line.startswith("#")]
    assert block.endswith("\n")


def test_registry_derives_grammar_tokens_for_every_function_id() -> None:
    assert set(EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY) == {
        ("workflow", "execution-instruction", "create"),
        ("workflow", "execution-instruction", "update"),
        ("workflow", "execution-instruction", "set-scope"),
        ("workflow", "execution-instruction", "resolve"),
        ("workflow", "execution-instruction", "list"),
        ("workflow", "execution-instruction", "delete"),
    }
    for tokens, (
        function_id,
        adapter,
    ) in EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY.items():
        assert function_id in USAGE_BY_FUNCTION_ID
        assert callable(adapter)
        assert tokens == tuple(function_id.replace("_", "-").split("."))


def test_resolve_dispatches_the_scope_and_renders_only_matching_prose(
    monkeypatch,
) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(adapters, "dispatch_and_emit", _dispatch)
    assert (
        adapters.workflow_execution_instruction_resolve(
            [
                "--workflow",
                "dash",
                "--project",
                "acme",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "workflow.execution_instruction.resolve"
    assert captured["target"].kind == "global"
    assert captured["payload"] == {
        "workflow": "dash",
        "project": "acme",
        "detail": "summary",
    }
    assert USAGE_BY_FUNCTION_ID[captured["function_id"]] == (
        "yoke workflow execution-instruction resolve "
        "--workflow W --project P [--delivery-point POINT] [--stage-bucket B] [--full] [--json]"
    )

    # The default names what binds the scope and how to read it.
    stdout = io.StringIO()
    captured["human_writer"](
        SimpleNamespace(
            success=True,
            result={
                "detail": "summary",
                "execution_instructions": [
                    {"id": 4, "title": "Obey me.", "read": "yoke ... --full"},
                ],
            },
        ),
        stdout,
        io.StringIO(),
    )
    scanned = stdout.getvalue()
    assert "4  Obey me." in scanned
    assert "Read them in full: yoke ... --full" in scanned
    assert EXECUTION_INSTRUCTION_BLOCK_HEADER not in scanned

    assert (
        adapters.workflow_execution_instruction_resolve(
            [
                "--workflow",
                "dash",
                "--project",
                "acme",
                "--full",
            ]
        )
        == 0
    )
    assert captured["payload"]["detail"] == "full"

    stdout = io.StringIO()
    captured["human_writer"](
        SimpleNamespace(
            success=True,
            result={
                "detail": "full",
                "execution_instructions": [{"content": "Obey me."}],
            },
        ),
        stdout,
        io.StringIO(),
    )
    assert EXECUTION_INSTRUCTION_BLOCK_HEADER in stdout.getvalue()
    assert "Obey me." in stdout.getvalue()


def test_delivery_flags_forward_partial_settings_on_every_write(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        adapters, "dispatch_and_emit", lambda **kwargs: captured.update(kwargs) or 0
    )
    flags = [
        "--no-before-creation",
        "--no-on-every-read",
        "--when-entering-stage",
        "--stage-bucket",
        "reviewing",
    ]
    for adapter, base in (
        (adapters.workflow_execution_instruction_create, ["--content", "Rule"]),
        (adapters.workflow_execution_instruction_update, ["4", "--content", "Rule"]),
        (adapters.workflow_execution_instruction_set_scope, ["4", "--all-workflows"]),
    ):
        assert adapter(base + flags) == 0
        assert captured["payload"]["before_creation"] is False
        assert captured["payload"]["on_every_read"] is False
        assert captured["payload"]["when_entering_stage"] is True
        assert captured["payload"]["stage_buckets"] == ["reviewing"]
    assert (
        adapters.workflow_execution_instruction_update(["4", "--content", "Rule"]) == 0
    )
    assert "before_creation" not in captured["payload"]
    assert (
        adapters.workflow_execution_instruction_set_scope(
            ["4", "--clear-stage-buckets", "--no-when-entering-stage"]
        )
        == 0
    )
    assert captured["payload"]["stage_buckets"] == []


def test_transition_prose_is_rendered_in_full():
    stdout = io.StringIO()
    adapters.write_transition_instructions(
        SimpleNamespace(
            success=True,
            result={
                "to_status": "implementing",
                "execution_instructions": [{"content": "Entry rule"}],
            },
        ),
        stdout,
        io.StringIO(),
    )
    assert "Entry rule" in stdout.getvalue()
    assert '"execution_instructions"' not in stdout.getvalue()


@pytest.mark.parametrize("fields", [[], ["spec"], ["spec", "--section", "## Scope"]])
def test_item_reads_deliver_operator_prose_once(fields):
    from yoke_cli.commands.adapters import items

    prose = "Keep the required safeguards. " * 100
    instruction = {"id": 4, "content": prose, "on_every_read": True}
    result = {
        "item_id": 17,
        "fields": {"spec": "Specification"},
        "execution_instructions": [instruction],
        "section_found": True,
        "content": "## Scope\nSpecification",
    }
    output = io.StringIO()

    def dispatch(**kwargs):
        kwargs["human_writer"](
            SimpleNamespace(success=True, result=result), output, io.StringIO()
        )
        return 0

    with patch.object(items, "dispatch_and_emit", side_effect=dispatch):
        assert items.items_get(["EX-1", *fields]) == 0
    rendered = output.getvalue()
    assert rendered.count(prose.rstrip()) == 1
    assert len(rendered) <= len(prose) + 750
    assert instruction["content"] == prose
    if not fields:
        receipt = json.loads(rendered.splitlines()[-1])
        descriptor = receipt["execution_instructions"][0]
        assert descriptor["id"] == 4
        assert descriptor["content_characters"] == len(prose)
        assert descriptor["read"] == "yoke items get EX-1 --json"
        assert descriptor["on_every_read"] is True
        assert "content" not in descriptor


def test_json_item_read_retains_the_complete_instruction_envelope(monkeypatch, capsys):
    from yoke_cli.main import main
    from yoke_contracts.api.function_call import FunctionCallResponse

    instruction = {"id": 4, "content": "Required operator rule", "on_every_read": True}

    def dispatch(**kwargs):
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            request_id="instruction-read",
            result={
                "fields": {"spec": "Specification"},
                "execution_instructions": [instruction],
            },
        )

    monkeypatch.setattr("yoke_cli.commands._helpers.call_dispatcher", dispatch)
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.ensure_handlers_loaded", lambda: None
    )
    assert main(["items", "get", "EX-1", "--json"]) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["result"]["execution_instructions"] == [instruction]
