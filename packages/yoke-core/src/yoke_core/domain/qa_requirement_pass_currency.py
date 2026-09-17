"""Whether a passing QA run still proves the live method_config.

Historical ``qa_runs`` rows stay immutable. A configuration change records a
later correction marker so an obsolete green cannot satisfy the new contract.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.schema_common import _column_exists


METHOD_CONFIG_FIELD = "method_config"
METHOD_CONFIG_CORRECTION_KEY = "method_config_correction"
PREVIOUS_METHOD_CONFIG_KEY = "previous_method_config"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def canonical_method_config(raw: Any) -> str:
    """Return the stable JSON form used for storage and comparison."""
    return canonical(_json_object(raw))


def attach_method_config_snapshot(raw_result: Optional[str], config: Any) -> str:
    """Persist the configuration a run executed, beside other evidence."""
    payload = _json_object(raw_result)
    if not payload and str(raw_result or "").strip():
        try:
            json.loads(str(raw_result))
        except (TypeError, ValueError):
            payload = {"evidence": str(raw_result).strip()}
    payload[METHOD_CONFIG_FIELD] = _json_object(config)
    return canonical(payload)


def is_method_config_correction(raw_result: Any) -> bool:
    return bool(_json_object(raw_result).get(METHOD_CONFIG_CORRECTION_KEY))


def recorded_method_config(raw_result: Any) -> dict[str, Any] | None:
    """Return the config a passing run proved, if it recorded one."""
    payload = _json_object(raw_result)
    if payload.get(METHOD_CONFIG_CORRECTION_KEY):
        return None
    config = payload.get(METHOD_CONFIG_FIELD)
    return dict(config) if isinstance(config, dict) else None


def has_current_passing_run(conn: Any, requirement_id: int) -> bool:
    """True when a pass still proves the requirement's live method_config."""
    from yoke_core.domain.db_helpers import query_one, query_rows

    marker = _marker(conn)
    if not _column_exists(conn, "qa_requirements", "method_config"):
        found = query_one(
            conn,
            "SELECT 1 AS ok FROM qa_runs "
            f"WHERE qa_requirement_id={marker} AND verdict='pass' LIMIT 1",
            (int(requirement_id),),
        )
        return found is not None
    row = query_one(
        conn,
        f"SELECT method_config FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    )
    if row is None:
        return False
    current = canonical_method_config(row["method_config"])
    runs = query_rows(
        conn,
        "SELECT id, verdict, raw_result FROM qa_runs "
        f"WHERE qa_requirement_id={marker} ORDER BY id",
        (int(requirement_id),),
    )
    correction_ids = [
        int(run["id"]) for run in runs if is_method_config_correction(run["raw_result"])
    ]
    for run in runs:
        if str(run["verdict"] or "") != "pass":
            continue
        recorded = recorded_method_config(run["raw_result"])
        run_id = int(run["id"])
        if recorded is not None:
            if canonical_method_config(recorded) == current:
                return True
            continue
        if any(marker_id > run_id for marker_id in correction_ids):
            continue
        return True
    return False


__all__ = [
    "METHOD_CONFIG_CORRECTION_KEY",
    "METHOD_CONFIG_FIELD",
    "PREVIOUS_METHOD_CONFIG_KEY",
    "attach_method_config_snapshot",
    "canonical_method_config",
    "has_current_passing_run",
    "is_method_config_correction",
    "recorded_method_config",
]
