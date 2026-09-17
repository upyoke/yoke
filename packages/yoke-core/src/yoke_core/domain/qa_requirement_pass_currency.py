"""Whether a passing QA run still proves the live method_config.

Historical ``qa_runs`` rows stay immutable. A run records the configuration
it started under inside ``raw_result``; complete keeps that start-bound
snapshot. An unstamped legacy pass still counts only while live config
matches the plan-case origin snapshot (or live config is empty).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.schema_common import _column_exists


METHOD_CONFIG_FIELD = "method_config"
PRESERVED_JSON_FIELD = "raw_result"
EVIDENCE_FIELD = "evidence"


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


def _parse_json_value(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def canonical_method_config(raw: Any) -> str:
    """Return the stable JSON form used for storage and comparison."""
    return canonical(_json_object(raw))


def attach_method_config_snapshot(
    raw_result: Optional[str],
    config: Any,
    *,
    overwrite: bool = False,
) -> str:
    """Persist the configuration a run started under, beside other evidence.

    Non-object JSON keeps its parsed value under ``raw_result``. An existing
    ``method_config`` snapshot is left in place unless ``overwrite`` is set.
    """
    snapshot = _json_object(config)
    parsed = _parse_json_value(raw_result)
    if isinstance(parsed, dict):
        payload = dict(parsed)
        existing = payload.get(METHOD_CONFIG_FIELD)
        if overwrite or not isinstance(existing, dict):
            payload[METHOD_CONFIG_FIELD] = snapshot
        return canonical(payload)
    payload: dict[str, Any] = {METHOD_CONFIG_FIELD: snapshot}
    if parsed is not None:
        payload[PRESERVED_JSON_FIELD] = parsed
    else:
        evidence = str(raw_result or "").strip()
        if evidence:
            payload[EVIDENCE_FIELD] = evidence
    return canonical(payload)


def stamp_executed_method_config(
    raw_result: Optional[str], config: Any
) -> Optional[str]:
    """Stamp start-bound config when the executed contract is non-empty."""
    if not _json_object(config):
        return raw_result
    return attach_method_config_snapshot(raw_result, config)


def retain_start_bound_method_config(existing_raw: Any, incoming_raw: str) -> str:
    """Keep the start-bound snapshot when later evidence replaces raw_result."""
    start = recorded_method_config(existing_raw)
    if start is None:
        return incoming_raw
    return attach_method_config_snapshot(incoming_raw, start, overwrite=True)


def recorded_method_config(raw_result: Any) -> dict[str, Any] | None:
    """Return the config a run recorded at start, if it recorded one."""
    config = _json_object(raw_result).get(METHOD_CONFIG_FIELD)
    return dict(config) if isinstance(config, dict) else None


def _plan_case_origin_config(conn: Any, requirement_id: int) -> dict[str, Any] | None:
    from yoke_core.domain.db_helpers import query_one

    if not _column_exists(conn, "qa_plan_cases", "method_config"):
        return None
    marker = _marker(conn)
    row = query_one(
        conn,
        "SELECT c.method_config AS origin FROM qa_requirements q "
        "JOIN qa_plan_cases c ON c.plan_id = q.plan_id "
        f"AND c.case_key = q.plan_case_key WHERE q.id={marker}",
        (int(requirement_id),),
    )
    if row is None or row["origin"] in (None, ""):
        return None
    return _json_object(row["origin"])


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
    origin = _plan_case_origin_config(conn, int(requirement_id))
    unstamped_still_current = current == canonical_method_config({}) or (
        origin is not None and canonical_method_config(origin) == current
    )
    runs = query_rows(
        conn,
        "SELECT verdict, raw_result FROM qa_runs "
        f"WHERE qa_requirement_id={marker} ORDER BY id",
        (int(requirement_id),),
    )
    for run in runs:
        if str(run["verdict"] or "") != "pass":
            continue
        recorded = recorded_method_config(run["raw_result"])
        if recorded is not None:
            if canonical_method_config(recorded) == current:
                return True
            continue
        if unstamped_still_current:
            return True
    return False


__all__ = [
    "EVIDENCE_FIELD",
    "METHOD_CONFIG_FIELD",
    "PRESERVED_JSON_FIELD",
    "attach_method_config_snapshot",
    "canonical_method_config",
    "has_current_passing_run",
    "recorded_method_config",
    "retain_start_bound_method_config",
    "stamp_executed_method_config",
]
