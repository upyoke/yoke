"""Read active Codex permissions from native session metadata, never saved config."""

from __future__ import annotations

from uuid import UUID

from yoke_contracts.harness_family_identity import CODEX_FAMILY, family_env_session_id
from yoke_contracts.harness_posture_read import posture_findings
from yoke_contracts.harness_sandbox_recovery import running_harness_family
from yoke_contracts.harness_unattended_posture import POSTURE_RECOVERY, codex_posture_problems
from yoke_contracts.refusal_recovery import compose_refusal
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


def read_codex_session_posture(
    session_id: str, *, turn_id: str = "", tool_use_id: str = ""
) -> tuple[dict | None, str]:
    """Return only permission metadata, bounded to the newest transcript's tail.

    Identity is checked inside the native artifact as well as in its filename.
    Missing, truncated or oversized evidence never falls back to saved config,
    another transcript, or an older turn's permission statement.
    Hook callers can bind the lookup to the active turn or its native tool ID.
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
        matched_tool = False
        for row in tail_rows_newest_first(transcript, record_factory=_PostureRecord):
            if row.get("type") == "posture_unreadable":
                return None, "newest transcript evidence is incomplete or unreadable"
            if turn_id or tool_use_id:
                payload = row.get("payload")
                if isinstance(payload, dict):
                    if row.get("type") == "event_msg" and payload.get("type") in {
                        "task_started",
                        "task_complete",
                        "turn_aborted",
                    }:
                        return None, "the active turn's permission statement is unavailable"
                    if (
                        tool_use_id
                        and row.get("type") == "response_item"
                        and payload.get("type") in {"function_call", "custom_tool_call"}
                        and payload.get("call_id") == tool_use_id
                    ):
                        matched_tool = True
            if row.get("type") != "turn_context":
                continue
            context = row.get("payload")
            if not isinstance(context, dict):
                return None, "newest turn has no permission metadata"
            recorded_turn = context.get("turn_id")
            if turn_id and recorded_turn and recorded_turn != turn_id:
                return None, "newest permission statement belongs to a different turn"
            if (turn_id or tool_use_id) and not (
                (turn_id and turn_id == recorded_turn) or matched_tool
            ):
                return None, "the tool call is not recorded in the newest turn"
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


def ambient_codex_session_id() -> str | None:
    """Identify the process's native thread without contacting Yoke's database."""
    session_id = family_env_session_id(CODEX_FAMILY)
    if session_id and running_harness_family() == CODEX_FAMILY:
        return session_id
    return None


def codex_posture_recovery(command: str | None = None) -> str:
    """Repair saved defaults only when they are known to be restricted."""
    retry = f"`{command}`" if command else "the command"
    recovery = (
        "Select Full Access in this thread's permissions control, then rerun "
        f"{retry} in a new turn. If organization policy prevents Full Access, "
        "ask your administrator."
    )
    if posture_findings(CODEX_FAMILY):
        return f"From a terminal outside this thread: {POSTURE_RECOVERY} {recovery}"
    return recovery


def codex_session_posture(
    session_id: str, *, command: str | None = None
) -> tuple[str, str]:
    facts, reason = read_codex_session_posture(session_id)
    if facts is None:
        retry = f"`{command}`" if command else "the command"
        return "HARNESS_POSTURE_UNVERIFIED", compose_refusal(
            reason,
            recovery=f"rerun {retry} in a new turn after it is saved; "
            "if it persists, start a new chat and try again",
        )
    problems = codex_posture_problems(facts)
    if problems:
        return "HARNESS_POSTURE_RESTRICTED", compose_refusal(
            ". ".join(problems),
            recovery=codex_posture_recovery(command),
        )
    return "", "records never and danger-full-access for this turn."
