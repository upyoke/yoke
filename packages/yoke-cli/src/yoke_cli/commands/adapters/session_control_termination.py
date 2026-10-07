"""CLI adapter for permanent top-level session termination."""

from __future__ import annotations

import argparse
from typing import Any, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import write_summary
from yoke_contracts.api.function_call import TargetRef


SESSION_TERMINATE_USAGE = (
    "yoke sessions terminate SESSION-ID --reason R [--allow-resume-in-flight] [--json]"
)
SESSION_TERMINATE_DESCRIPTION = (
    "Permanently end one top-level session, cancel its undelivered "
    "messages, request best-effort native-process reaping, and release "
    "the session's held work claims. A session a wake is resuming is "
    "refused as TERMINATION_RESUME_IN_FLIGHT: a headless worker's process "
    "exits between turns and a message resumes it from its transcript, so "
    "message it instead."
)


def _write_termination_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    session = result.get("session") or {}
    write_summary(
        "SESSION TERMINATION",
        (
            ("SESSION", session.get("session_id")),
            ("TERMINATED", session.get("terminated_at")),
            ("CANCELLED RECIPIENTS", result.get("cancelled_recipient_count", 0)),
            ("REAP", result.get("reap_state")),
            ("DEDUPLICATED", bool(result.get("deduplicated"))),
        ),
        stdout,
    )


def session_terminate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions terminate",
        usage=SESSION_TERMINATE_USAGE,
        description=SESSION_TERMINATE_DESCRIPTION,
    )
    parser.add_argument("target_session_id", metavar="SESSION-ID")
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--allow-resume-in-flight",
        action="store_true",
        help=(
            "Terminate even while a wake is resuming the session. Use only "
            "with evidence it cannot resume, or for a deliberate restaff."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_TERMINATE_USAGE)
    if parsed is None:
        return 2
    payload = {
        "session_id": parsed.target_session_id,
        "reason": parsed.reason,
    }
    if parsed.allow_resume_in_flight:
        # Sent only when set, so an ordinary termination stays readable by a
        # serving build whose request contract predates the field.
        payload["allow_resume_in_flight"] = True
    return dispatch_and_emit(
        function_id="session_control.session.terminate",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_termination_result,
    )


__all__ = [
    "SESSION_TERMINATE_DESCRIPTION",
    "SESSION_TERMINATE_USAGE",
    "session_terminate",
]
