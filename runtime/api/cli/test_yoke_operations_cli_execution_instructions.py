"""CLI rendering of the operator execution-instruction block."""

from __future__ import annotations

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


def test_block_is_labeled_with_one_subheader_per_instruction() -> None:
    block = render_execution_instruction_block([
        {"title": "Run doctor first", "content": "Always run doctor.\n"},
        {"title": "Mind the gate", "content": "QA gate is mandatory."},
    ])

    lines = block.splitlines()
    assert lines[0] == EXECUTION_INSTRUCTION_BLOCK_HEADER
    assert "## Run doctor first" in lines
    assert "## Mind the gate" in lines
    assert "Always run doctor." in lines
    assert "QA gate is mandatory." in lines
    assert block.endswith("\n")


def test_registry_derives_grammar_tokens_for_every_function_id() -> None:
    assert set(EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY) == {
        ("workflow", "execution-instruction", "create"),
        ("workflow", "execution-instruction", "update"),
        ("workflow", "execution-instruction", "set-scope"),
        ("workflow", "execution-instruction", "list"),
        ("workflow", "execution-instruction", "delete"),
    }
    for tokens, (function_id, adapter) in (
        EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY.items()
    ):
        assert function_id in USAGE_BY_FUNCTION_ID
        assert callable(adapter)
        assert tokens == tuple(function_id.replace("_", "-").split("."))
