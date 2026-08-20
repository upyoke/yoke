"""Handler registrations for ``workflow.execution_instruction.*``.

Operator-authored execution instructions scoped by workflow and project:
``create``, ``update``, ``set_scope``, ``resolve``, ``list``, and ``delete``.
"""
from __future__ import annotations

from yoke_core.domain.handlers import workflow_execution_instructions_crud


def register(registry) -> None:
    """Register the execution-instruction handlers via the given registry."""
    for entry in workflow_execution_instructions_crud.REGISTRATIONS:
        registry.register(**entry)
