"""Resume evidence used when a QA owner's native process is confirmed gone."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_contracts.session_control.resume import RESUME_TERMINAL_RESULTS

from .db_helpers import instant_parameter, query_one
from .session_message_types import parse_timestamp
from .session_relay_storage import marker
from .session_resume_in_flight import (
    WAKE_RELAY_ATTEMPT_KIND,
    resumable_from_transcript,
)


def qa_owner_can_resume(conn: Any, session: Mapping[str, Any]) -> bool:
    """Keep the transcript available until a resume of this exit fails."""
    surface = session.get("executor_surface")
    if not native_wake_supported(surface, session.get("launch_origin")):
        return False
    if not resumable_from_transcript(surface, session.get("executor_version")):
        return False
    gone = parse_timestamp(session.get("native_process_gone_at"))
    if gone is None:
        return True
    p = marker(conn)
    attempt = query_one(
        conn,
        "SELECT result_code FROM session_message_attempts "
        f"WHERE target_session_id={p} AND attempt_kind={p} AND started_at>={p} "
        "ORDER BY started_at DESC,attempt_id DESC LIMIT 1",
        (session["session_id"], WAKE_RELAY_ATTEMPT_KIND, instant_parameter(conn, gone)),
    )
    return attempt is None or attempt["result_code"] not in {
        "failed", *RESUME_TERMINAL_RESULTS,
    }
