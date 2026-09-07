"""Persist what a session has consumed, without ever unlearning a total.

Consumption arrives the same two ways a served model does. A relayed hook
carries the reading its own machine took, because only that machine can
see the harness artifact. A local hook carries nothing, so the reading is
taken here — the same process, the same machine, the same artifact.

Two write rules keep the stored figure honest:

* A reading that measured something always replaces what is stored. The
  reading is cumulative for the whole session, so a later one is simply a
  better answer to the same question, and replacement is what makes
  repeated observation safe — nothing here ever adds.
* A reading that measured nothing writes only where nothing has been
  measured yet. Its value is the reason it carries, which is what an
  operator reads instead of a total; overwriting a real total with it
  would turn a session that ran into one that apparently did not.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_usage_facts import (
    usage_document,
    usage_from_document,
)
from yoke_core.domain import db_backend


USAGE_COLUMN = "usage_totals"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _payload(payload_json: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(payload_json) if payload_json else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def observed_usage_document(payload_json: str, executor: str) -> str:
    """Return the reading this hook event carries, or could take itself.

    A relayed payload already holds one, taken on the machine that can
    read the artifact. A local payload holds none, and this process is
    that machine, so the reading is taken here. Failing to read anything
    returns ``""``, which writes nothing at all — distinct from a reading
    that proved nothing, which writes its reason.
    """
    payload = _payload(payload_json)
    carried = payload.get(USAGE_COLUMN)
    if isinstance(carried, str) and carried.strip():
        return carried
    if not executor:
        return ""
    try:
        from yoke_harness.usage_attestation import attest_session_usage

        transcript = payload.get("transcript_path")
        usage = attest_session_usage(
            executor,
            payload,
            transcript_path=transcript if isinstance(transcript, str) else "",
        )
    except Exception:  # noqa: BLE001 — usage observation never breaks a hook
        return ""
    return usage_document(usage)


def record_session_usage(
    conn: Any,
    *,
    session_id: str,
    payload_json: str,
    executor: str = "",
) -> bool:
    """Store a newer reading; a repeated one stays write-free."""
    document = observed_usage_document(payload_json, executor)
    if conn is None or not session_id or not document:
        return False
    incoming = usage_from_document(document)
    if incoming is None:
        return False
    marker = _marker(conn)
    row = conn.execute(
        f"SELECT {USAGE_COLUMN} FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    stored_document = row[0]
    if stored_document == document:
        return False
    if not incoming.measured():
        stored = usage_from_document(stored_document)
        if stored is not None and stored.measured():
            return False
    conn.execute(
        f"UPDATE harness_sessions SET {USAGE_COLUMN}={marker} "
        f"WHERE session_id={marker}",
        (document, session_id),
    )
    conn.commit()
    return True


__all__ = ["USAGE_COLUMN", "observed_usage_document", "record_session_usage"]
