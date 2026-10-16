"""Remove one-time token results from replay receipts and debug telemetry.

The ledger checksum binds the request, not its result, so redaction preserves
that checksum and every receipt identity. Event envelopes retain their writer's
JSON encoding and all fields except the secret-bearing context result.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from yoke_core.domain.admission_result_redaction import ONE_TIME_SECRET_GUARDRAIL
from yoke_core.domain import db_backend
from yoke_core.domain.function_call_ledger import serialize_result
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists


# Older serving builds would retain newly minted secrets again.
MINIMUM_SERVING_VERSION = NEXT_RELEASE
REDACTED_RESULT = {"result_redacted": ONE_TIME_SECRET_GUARDRAIL}


def _object(raw: Any) -> dict | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _rows(conn: Any, table: str, query: str) -> Iterator[Any]:
    if not _table_exists(conn, table):
        return
    cursor = conn.execute(query)
    while rows := cursor.fetchmany(500):
        yield from rows


def _ledger_secrets(conn: Any) -> Iterator[Any]:
    for request_id, raw in _rows(
        conn, "function_call_ledger",
        "SELECT request_id, result FROM function_call_ledger "
        "WHERE function_id = 'profile.token.create'",
    ):
        result = _object(raw)
        if result is not None and "raw_token" in result:
            yield request_id


def _event_secrets(conn: Any) -> Iterator[Any]:
    for event_id, raw in _rows(
        conn, "events",
        "SELECT id, envelope FROM events WHERE event_name = 'YokeFunctionCalled'",
    ):
        envelope = _object(raw)
        context = envelope.get("context") if envelope is not None else None
        if not isinstance(context, dict) or context.get("function") != "profile.token.create":
            continue
        result = context.get("result")
        if isinstance(result, dict) and "raw_token" in result:
            yield event_id, envelope


def apply(conn: Any) -> None:
    """Scrub matching results once, leaving the transaction to the runner."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ledger_count = event_count = 0
    for request_id in _ledger_secrets(conn):
        ledger_count += conn.execute(
            f"UPDATE function_call_ledger SET result = {placeholder} "
            f"WHERE request_id = {placeholder}",
            (serialize_result(REDACTED_RESULT), request_id),
        ).rowcount
    for event_id, envelope in _event_secrets(conn):
        envelope["context"]["result"] = dict(REDACTED_RESULT)
        # Match events_write_conn.event_insert_params without rewriting its
        # already-stored timestamp or any other envelope metadata.
        event_count += conn.execute(
            f"UPDATE events SET envelope = {placeholder} WHERE id = {placeholder}",
            (json.dumps(envelope), event_id),
        ).rowcount
    print(
        f"admission_secret_receipts ledger_rows_rewritten={ledger_count} "
        f"event_envelopes_rewritten={event_count}",
        flush=True,
    )


def invariants(conn: Any) -> None:
    """Require no matching result to retain a raw-token field."""
    ledger_count = sum(1 for _ in _ledger_secrets(conn))
    event_count = sum(1 for _ in _event_secrets(conn))
    assert ledger_count == event_count == 0, (
        "one-time secret receipts remain: "
        f"ledger_rows={ledger_count}, event_envelopes={event_count}"
    )
