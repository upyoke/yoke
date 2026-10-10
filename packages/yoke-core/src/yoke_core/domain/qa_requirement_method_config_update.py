"""Validate an in-place ``method_config`` correction for one QA requirement.

Split from :mod:`qa_requirement_config_update`, which owns the update
dispatch. A frozen deployment-run row may be corrected only while its
correction window is open, and the new config is validated against the
method's registered config contract before anything is written.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_deployment_case_correction_window import (
    correction_window_closed_reason,
    correction_window_open,
)
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_requirement_frozen_snapshot import FROZEN_REQUIREMENT_CODE
from yoke_core.domain.qa_requirement_pass_currency import (
    _marker,
    executable_method_config,
)
from yoke_core.domain.schema_common import _table_exists


_BUILTIN_CONTRACTS = {
    str(method["id"]): str(method["config_contract_id"])
    for method in BUILTIN_QA_METHODS
}


def _config_contract_id(conn: Any, method_id: str) -> str | None:
    if _table_exists(conn, "qa_methods"):
        method = query_one(
            conn,
            f"SELECT config_contract_id FROM qa_methods WHERE id={_marker(conn)}",
            (str(method_id),),
        )
        if method is not None and method["config_contract_id"]:
            return str(method["config_contract_id"])
    return _BUILTIN_CONTRACTS.get(str(method_id))


def _prepare_method_config(
    conn: Any, existing: Any, value: Any
) -> tuple[Optional[str], str]:
    method_id = str(existing["method_id"] or "") if existing["method_id"] else ""
    if not method_id:
        return None, "method_config is only updatable on method-backed requirements"
    if existing["deployment_run_id"] and not correction_window_open(
        conn, int(existing["id"])
    ):
        # Frozen only once the case has actually answered. Before that the
        # row is a case nobody has judged, and correcting it is how a
        # wrong-target, missing-field or data-precondition defect gets
        # fixed at all -- those surface on the first real run, not by
        # reading the case.
        return None, (
            f"{FROZEN_REQUIREMENT_CODE}: "
            + correction_window_closed_reason(int(existing["id"]))
        )
    contract_id = _config_contract_id(conn, method_id)
    if contract_id is None:
        return None, f"method {method_id!r} is not registered"
    raw: Any = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError):
            return None, "method_config must be a JSON object"
    if isinstance(raw, dict):
        raw = executable_method_config(raw)
    try:
        config = validate_method_config(contract_id, raw)
    except QaMethodConfigError as exc:
        return None, str(exc)
    return canonical(config), ""
