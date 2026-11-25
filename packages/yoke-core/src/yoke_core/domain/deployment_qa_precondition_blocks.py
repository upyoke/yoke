"""Name why an unstarted case waits, so a repair alarm never reads as waiting.

A case blocked on a precondition has no verdict, so the gate grades it
``unrun``. Its line still names the run's error code and that code's
recovery: ``harness_provider_unavailable`` retries by itself, while
``machine_needs_repair`` needs a person at the host.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker

GENERIC_RECOVERY = "resolve the named precondition; the case runs with the next execution"


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(str(value or "{}"))
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _block(row: dict[str, Any]) -> tuple[str, str]:
    """A blocked run's error code and recovery, from either runner's shape."""
    raw = _json(row["raw_result"])
    preparation = _json(raw.get("preparation"))
    failure = _json(_json(preparation.get("evidence")).get("preparation_failure"))
    reset = _json(_json(raw.get("evidence")).get("owed_reset"))
    reason = str(row["capture_degraded_reason"] or "")
    code = (
        raw.get("error_code")
        or preparation.get("error_code")
        or reason.split(":", 1)[0]
        or "blocked_on_precondition"
    )
    recovery = failure.get("recovery") or reset.get("recovery") or GENERIC_RECOVERY
    return str(code), str(recovery)


def precondition_notes(conn: Any, run_ids: Iterable[int]) -> dict[int, str]:
    """Each unstarted, unjudged run's note, keyed by its run id."""
    ids = sorted({int(run_id) for run_id in run_ids})
    if not ids:
        return {}
    p = marker(conn)
    rows = query_rows(
        conn,
        "SELECT id,raw_result,capture_degraded_reason FROM qa_runs "
        f"WHERE id IN ({','.join(p for _ in ids)}) AND verdict IS NULL "
        "AND case_outcome='blocked_on_precondition'",
        tuple(ids),
    )
    notes = {}
    for row in rows:
        code, recovery = _block(dict(row))
        notes[int(row["id"])] = f" (blocked_on_precondition: {code}; {recovery})"
    return notes


__all__ = ["GENERIC_RECOVERY", "precondition_notes"]
