"""Validation for method-backed QA requirement rows."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import HandlerOutcome

from yoke_core.domain.handlers.qa import _error, _p


def validate_method_requirement(
    conn: Any,
    row: Dict[str, Any],
    jsonpath: str,
) -> Optional[HandlerOutcome]:
    """Validate a registered method case and derive its safe storage fields."""
    method_id = row.get("method_id")
    if not method_id:
        return None
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    p = _p(conn)
    method = query_one(
        conn,
        "SELECT name, runner_id, verdict_path, required_capability_kind, "
        "config_contract_id "
        f"FROM qa_methods WHERE id={p}",
        (str(method_id),),
    )
    if method is None:
        return _error(
            "payload_invalid",
            f"method {method_id!r} is not registered",
            jsonpath=f"{jsonpath}.method_id",
        )
    instructions = row.get("instructions")
    expected = row.get("expected_outcome")
    if not isinstance(instructions, str) or not instructions.strip():
        return _error(
            "payload_invalid",
            "method-backed cases require instructions",
            jsonpath=f"{jsonpath}.instructions",
        )
    if not isinstance(expected, str) or not expected.strip():
        return _error(
            "payload_invalid",
            "method-backed cases require expected_outcome",
            jsonpath=f"{jsonpath}.expected_outcome",
        )
    try:
        row["method_config"] = validate_method_config(
            str(method["config_contract_id"]),
            row.get("method_config"),
        )
    except QaMethodConfigError as exc:
        return _error(
            "payload_invalid",
            str(exc),
            jsonpath=f"{jsonpath}.method_config",
        )
    capability = method["required_capability_kind"]
    row["capability_requirements"] = json.dumps(
        [str(capability)] if capability else [],
        sort_keys=True,
    )
    row["method_name"] = str(method["name"])
    row["runner_id"] = str(method["runner_id"])
    row["required_capability_kind"] = capability
    row["verdict_path"] = str(method["verdict_path"])
    return None


__all__ = ["validate_method_requirement"]
