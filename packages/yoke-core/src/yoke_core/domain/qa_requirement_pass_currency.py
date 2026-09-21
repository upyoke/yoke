"""Whether a passing QA run still proves the live method_config and target.

Historical ``qa_runs`` rows stay immutable. A run records the executable
configuration and execution-target digest it started under inside
``raw_result``; complete keeps those start-bound snapshots. An in-place
``method_config`` correction records a revision marker on the requirement;
once set it stays, including through empty config, and unstamped greens then
no longer satisfy. Compare and execute the config with that marker stripped.
A live execution-target digest is proved only by a pass that recorded the
same digest, or the digest a sanctioned rebind moved the row from.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.schema_common import _column_exists


METHOD_CONFIG_FIELD = "method_config"
METHOD_CONFIG_REVISION_KEY = "_corrected"
EXECUTION_TARGET_DIGEST_FIELD = "execution_target_digest"
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


def executable_method_config(raw: Any) -> dict[str, Any]:
    """Return stored method_config without the in-place revision marker."""
    payload = _json_object(raw)
    payload.pop(METHOD_CONFIG_REVISION_KEY, None)
    return payload


def method_config_was_corrected(raw: Any) -> bool:
    """True when this requirement's method_config was revised in place."""
    return METHOD_CONFIG_REVISION_KEY in _json_object(raw)


def canonical_method_config(raw: Any) -> str:
    """Return the stable executable JSON form used for storage and comparison."""
    return canonical(executable_method_config(raw))


def bind_correction_identity(
    previous: Any, prepared_canonical: str, *, force: bool = False
) -> str:
    """Keep a durable revision marker once executable config has changed."""
    payload = executable_method_config(prepared_canonical)
    if (
        force
        or method_config_was_corrected(previous)
        or (canonical_method_config(previous) != prepared_canonical)
    ):
        payload[METHOD_CONFIG_REVISION_KEY] = True
    return canonical(payload)


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
    snapshot = executable_method_config(config)
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


def attach_execution_target_digest(
    raw_result: Optional[str], digest: str, *, overwrite: bool = False
) -> str:
    """Persist the target digest a run started under, beside other evidence."""
    value = str(digest or "").strip()
    parsed = _parse_json_value(raw_result)
    if isinstance(parsed, dict):
        payload = dict(parsed)
        if overwrite or not str(payload.get(EXECUTION_TARGET_DIGEST_FIELD) or ""):
            payload[EXECUTION_TARGET_DIGEST_FIELD] = value
        return canonical(payload)
    payload: dict[str, Any] = {EXECUTION_TARGET_DIGEST_FIELD: value}
    if parsed is not None:
        payload[PRESERVED_JSON_FIELD] = parsed
    else:
        evidence = str(raw_result or "").strip()
        if evidence:
            payload[EVIDENCE_FIELD] = evidence
    return canonical(payload)


def stamp_executed_method_config(
    raw_result: Optional[str],
    config: Any,
    *,
    execution_target_digest: str | None = None,
    conn: Any = None,
    requirement_id: int | None = None,
) -> Optional[str]:
    """Stamp start-bound executable config and target digest when present."""
    digest = str(execution_target_digest or "").strip()
    if not digest and conn is not None and requirement_id is not None:
        digest = _live_execution_target_digest(conn, int(requirement_id))
    if not executable_method_config(config) and not digest:
        return raw_result
    stamped = raw_result
    if executable_method_config(config):
        stamped = attach_method_config_snapshot(stamped, config)
    if digest:
        stamped = attach_execution_target_digest(stamped, digest)
    return stamped


def retain_start_bound_method_config(existing_raw: Any, incoming_raw: str) -> str:
    """Keep the start-bound snapshots when later evidence replaces raw_result."""
    start = recorded_method_config(existing_raw)
    digest = recorded_execution_target_digest(existing_raw)
    result = incoming_raw
    if start is not None:
        result = attach_method_config_snapshot(result, start, overwrite=True)
    if digest:
        result = attach_execution_target_digest(result, digest, overwrite=True)
    return result


def recorded_method_config(raw_result: Any) -> dict[str, Any] | None:
    """Return the executable config a run recorded at start, if it recorded one."""
    config = _json_object(raw_result).get(METHOD_CONFIG_FIELD)
    if not isinstance(config, dict):
        return None
    return executable_method_config(config)


def recorded_execution_target_digest(raw_result: Any) -> str:
    """Return the target digest a run recorded at start, if it recorded one."""
    return str(_json_object(raw_result).get(EXECUTION_TARGET_DIGEST_FIELD) or "")


def _live_execution_target_digest(conn: Any, requirement_id: int) -> str:
    from yoke_core.domain.db_helpers import query_one

    if not _column_exists(conn, "qa_requirements", EXECUTION_TARGET_DIGEST_FIELD):
        return ""
    row = query_one(
        conn,
        f"SELECT execution_target_digest FROM qa_requirements WHERE id={_marker(conn)}",
        (int(requirement_id),),
    )
    if row is None:
        return ""
    try:
        value = row["execution_target_digest"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(value or "")


def has_current_passing_run(conn: Any, requirement_id: int) -> bool:
    """True when a pass still proves the live method_config and target."""
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
    digest_sql = ""
    rebind_sql = ""
    if _column_exists(conn, "qa_requirements", EXECUTION_TARGET_DIGEST_FIELD):
        digest_sql = ", execution_target_digest"
        if _column_exists(conn, "qa_requirements", "rebound_from_digest"):
            rebind_sql = ", rebound_from_digest, rebound_at"
    row = query_one(
        conn,
        f"SELECT method_config{digest_sql}{rebind_sql} FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    )
    if row is None:
        return False
    current = canonical_method_config(row["method_config"])
    corrected = method_config_was_corrected(row["method_config"])
    live_digest = str(row["execution_target_digest"] or "") if digest_sql else ""
    proving_digests = {live_digest} if live_digest else set()
    if rebind_sql:
        rebound_from = str(row["rebound_from_digest"] or "")
        if str(row["rebound_at"] or "") and rebound_from:
            proving_digests.add(rebound_from)
    runs = query_rows(
        conn,
        "SELECT verdict, raw_result FROM qa_runs "
        f"WHERE qa_requirement_id={marker} ORDER BY id",
        (int(requirement_id),),
    )
    for run in runs:
        if str(run["verdict"] or "") != "pass":
            continue
        recorded_digest = recorded_execution_target_digest(run["raw_result"])
        if live_digest and recorded_digest not in proving_digests:
            continue
        recorded = recorded_method_config(run["raw_result"])
        if recorded is not None:
            if canonical_method_config(recorded) == current:
                return True
            continue
        if not corrected:
            return True
    return False


__all__ = [
    "EVIDENCE_FIELD",
    "EXECUTION_TARGET_DIGEST_FIELD",
    "METHOD_CONFIG_FIELD",
    "METHOD_CONFIG_REVISION_KEY",
    "PRESERVED_JSON_FIELD",
    "attach_execution_target_digest",
    "attach_method_config_snapshot",
    "bind_correction_identity",
    "canonical_method_config",
    "executable_method_config",
    "has_current_passing_run",
    "method_config_was_corrected",
    "recorded_execution_target_digest",
    "recorded_method_config",
    "retain_start_bound_method_config",
    "stamp_executed_method_config",
]
