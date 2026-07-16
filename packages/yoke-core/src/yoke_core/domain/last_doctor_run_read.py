"""Read the most recent completed Doctor run out of the events journal.

Doctor findings persist nowhere as rows: ``doctor.run.run`` executes the
health checks and returns its report in the function-call response. The
only durable trace of a run is the dispatcher's ``YokeFunctionCalled``
event, whose envelope ``context`` carries the function id and the full
result payload. This module is the read behind ``doctor.last_run.get``:
newest-first over those journal rows, serving the first COMPLETE run —
a cursor-paginated partial page (``done: false``) is not a run.

Envelope honesty: the event layer's value-aware shrink
(:mod:`yoke_core.domain.events_envelope_shrink`) may have replaced an
oversized ``context.result`` with a ``{"_truncated_value": true}``
marker. Such a run is served with ``truncated: true``, empty
``results``, and only the facts that survived (``ran_at``); counts
inside a wholesale-replaced result are unrecoverable and serve as
``None`` rather than invented zeros.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from yoke_core.domain import db_helpers
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.project_identity import resolve_project


#: Function id whose journal envelopes carry Doctor reports.
DOCTOR_RUN_FUNCTION_ID = "doctor.run.run"

#: Journal rows fetched per scan page while walking newest-first.
SCAN_BATCH_SIZE = 200

#: Result keys served for each health-check row.
CHECK_RESULT_FIELDS = ("hc", "name", "severity", "detail")


def _scan_batch(
    conn: Any,
    cursor: Optional[Tuple[str, int]],
) -> List[Dict[str, Any]]:
    """One newest-first page of candidate journal rows.

    The LIKE prefilter is a coarse candidate cut only — any envelope
    whose ``context.function`` equals :data:`DOCTOR_RUN_FUNCTION_ID`
    necessarily contains the id as a substring regardless of JSON
    serialization; exact matching happens on the parsed envelope.
    """
    where = (
        "WHERE event_name = %s AND envelope IS NOT NULL "
        "AND envelope LIKE %s"
    )
    params: List[Any] = [
        "YokeFunctionCalled", f"%{DOCTOR_RUN_FUNCTION_ID}%",
    ]
    if cursor is not None:
        where += " AND (created_at < %s OR (created_at = %s AND id < %s))"
        params.extend([cursor[0], cursor[0], cursor[1]])
    rows = conn.execute(
        f"SELECT id, created_at, envelope FROM events {where} "
        "ORDER BY created_at DESC, id DESC LIMIT %s",
        (*params, SCAN_BATCH_SIZE),
    ).fetchall()
    return [dict(row) for row in rows]


def _doctor_result(envelope_text: str) -> Optional[Dict[str, Any]]:
    """The envelope's ``context.result`` when it records a doctor run.

    Returns the result dict (which may be a shrink marker), or ``None``
    when the envelope is unparseable, records a different function, or
    carries no dict-shaped context/result at all (e.g. the whole-context
    truncation fallback, which also loses the function id).
    """
    try:
        envelope = loads_text(envelope_text)
    except ValueError:
        return None
    if not isinstance(envelope, dict):
        return None
    context = envelope.get("context")
    if not isinstance(context, dict):
        return None
    if context.get("function") != DOCTOR_RUN_FUNCTION_ID:
        return None
    result = context.get("result")
    return result if isinstance(result, dict) else None


def _result_is_truncated(result: Dict[str, Any]) -> bool:
    return bool(result.get("_truncated_value"))


def _serve_truncated(ran_at: str) -> Dict[str, Any]:
    return {
        "never_run": False,
        "ran_at": ran_at,
        "scope": None,
        "project": None,
        "pass_count": None,
        "warn_count": None,
        "fail_count": None,
        "total": None,
        "results": [],
        "truncated": True,
    }


def _serve_run(ran_at: str, result: Dict[str, Any]) -> Dict[str, Any]:
    raw_results = result.get("results")
    checks = [
        {field: entry.get(field) for field in CHECK_RESULT_FIELDS}
        for entry in (raw_results if isinstance(raw_results, list) else [])
        if isinstance(entry, dict)
    ]
    return {
        "never_run": False,
        "ran_at": ran_at,
        "scope": result.get("scope"),
        "project": result.get("project"),
        "pass_count": int(result.get("pass_count") or 0),
        "warn_count": int(result.get("warn_count") or 0),
        "fail_count": int(result.get("fail_count") or 0),
        "total": len(checks),
        "results": checks,
        "truncated": False,
    }


def _accepted_project_names(conn: Any, project: str) -> Set[str]:
    """The stored-result spellings that count as a match for ``project``.

    ``result.project`` stores whatever the doctor caller passed —
    normally the slug — so a request by numeric id must also match the
    slug spelling (and vice versa). Raises ``LookupError`` for an
    unknown project, mirroring the other project-scoped reads.
    """
    ident = resolve_project(conn, project)
    assert ident is not None
    return {ident.slug, str(ident.id)}


def last_doctor_run(*, project: Optional[str] = None) -> Dict[str, Any]:
    """Serve the newest completed doctor run recorded in the journal.

    With no ``project``, the newest ``done: true`` run wins regardless
    of which project it checked. With a ``project`` (slug or id), only a
    run whose stored ``result.project`` matches is served — a mismatched
    or project-unreadable (truncated) run falls through to
    ``{"never_run": true}`` rather than posing as this project's report.
    """
    conn = db_helpers.connect()
    try:
        accepted = (
            _accepted_project_names(conn, project) if project else None
        )
        cursor: Optional[Tuple[str, int]] = None
        while True:
            batch = _scan_batch(conn, cursor)
            if not batch:
                return {"never_run": True}
            for row in batch:
                result = _doctor_result(str(row.get("envelope") or ""))
                if result is None:
                    continue
                ran_at = str(row.get("created_at") or "")
                if _result_is_truncated(result):
                    # The shrink kept the envelope but replaced the
                    # report; its project is unreadable, so it can
                    # never satisfy an explicit project filter.
                    if accepted is not None:
                        continue
                    return _serve_truncated(ran_at)
                if result.get("done") is not True:
                    continue
                if (
                    accepted is not None
                    and str(result.get("project")) not in accepted
                ):
                    continue
                return _serve_run(ran_at, result)
            last = batch[-1]
            cursor = (str(last["created_at"]), int(last["id"]))
    finally:
        conn.close()


__all__ = [
    "CHECK_RESULT_FIELDS",
    "DOCTOR_RUN_FUNCTION_ID",
    "SCAN_BATCH_SIZE",
    "last_doctor_run",
]
