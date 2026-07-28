"""CLI error shaping for QA requirement workflow-transition bindings."""

from __future__ import annotations

import sys
from typing import Any

from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    validate_item_qa_transition,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError


def require_cli_workflow_transition(
    conn: Any,
    *,
    item_id: int,
    transition_id: str | None,
    label: str | None = None,
) -> str:
    """Validate one QA binding and translate failures to CLI exit code 2."""
    try:
        transition, _workflow = validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
        )
    except (QaWorkflowBindingError, WorkflowRegistryError) as exc:
        prefix = f"{label}: " if label else ""
        print(f"Error: {prefix}{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    return transition


__all__ = ["require_cli_workflow_transition"]
