"""Mechanical registry entries for workflow execution instructions."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import (
    workflow_execution_instructions as adapters,
)


AdapterFn = Callable[[List[str]], int]
EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    tuple(function_id.replace("_", "-").split(".")): (
        function_id,
        getattr(adapters, function_id.replace(".", "_")),
    )
    for function_id in adapters.USAGE_BY_FUNCTION_ID
}


__all__ = ["EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY"]
