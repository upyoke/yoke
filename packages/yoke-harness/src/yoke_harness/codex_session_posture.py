"""Read active Codex permissions from native session metadata, never saved config."""

from __future__ import annotations

from uuid import UUID

from yoke_harness.artifact_record_stream import BufferedJsonRecord
from yoke_harness.artifact_scan import iter_rows, tail_rows_newest_first
from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates


class _PostureRecord(BufferedJsonRecord):
    """An unreadable newer record must not reveal an older permissive turn."""

    def finish(self) -> dict | None:
        row = super().finish()
        if row is None and self.record_bytes:
            return {"type": "posture_unreadable"}
        return row


def read_codex_session_posture(session_id: str) -> tuple[dict | None, str]:
    """Return only permission metadata, bounded to the newest transcript's tail.

    Identity is checked inside the native artifact as well as in its filename.
    Missing, truncated or oversized evidence never falls back to saved config,
    another transcript, or an older turn's permission statement.
    """
    try:
        if str(UUID(session_id)) != session_id:
            return None, "session identity is not a canonical UUID"
        candidates = codex_transcript_candidates(session_id)
        if not candidates:
            return None, "native session transcript is missing"
        transcript = candidates[0]
        first = next(iter_rows(transcript, record_factory=_PostureRecord), {})
        metadata = first.get("payload")
        if (
            first.get("type") != "session_meta"
            or not isinstance(metadata, dict)
            or metadata.get("id") != session_id
        ):
            return None, "native session metadata does not match this session"
        for row in tail_rows_newest_first(transcript, record_factory=_PostureRecord):
            if row.get("type") == "posture_unreadable":
                return None, "newest transcript evidence is incomplete or unreadable"
            if row.get("type") != "turn_context":
                continue
            context = row.get("payload")
            if not isinstance(context, dict):
                return None, "newest turn has no permission metadata"
            sandbox = context.get("sandbox_policy")
            sandbox = sandbox if isinstance(sandbox, dict) else {}
            return {
                "approval_policy": context.get("approval_policy"),
                "approvals_reviewer": context.get("approvals_reviewer"),
                "sandbox_mode": sandbox.get("type"),
            }, ""
    except (OSError, ValueError, TypeError):
        return None, "native session transcript could not be read"
    return None, "newest permission statement is outside the bounded transcript tail"
