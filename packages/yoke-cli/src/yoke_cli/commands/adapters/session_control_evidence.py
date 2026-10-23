"""CLI adapter for reading a machine's own evidence from any other seat."""

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
from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.session_control.evidence_fetch import (
    EVIDENCE_KINDS,
    EVIDENCE_TAIL_DEFAULT_LINES,
    EVIDENCE_TAIL_MAX_LINES,
    EVIDENCE_WAIT_DEFAULT_SECONDS,
    EVIDENCE_WAIT_MAX_SECONDS,
)
from yoke_contracts.session_control.function_ids import EVIDENCE_GET_FUNCTION_ID


EVIDENCE_GET_USAGE = (
    "yoke session-control evidence get --session SESSION-ID "
    "[--kind relay|watcher|diagnostic] [--file NAME] [--evidence-id ND-REF] "
    "[--tail N] [--wait-seconds N] [--session-id S] [--json]"
)
_DESCRIPTION = """Read one relay, watcher or diagnostic file from a session's machine.

Relay diagnostics, watcher captures and the relay's own logs stay on the
machine that wrote them. From another machine you can see that a launch or
wake failed, but not why. This command asks that machine's relay, the same
way wakes and launches are sent, for a list of the session's files and the
end of one file.

Which file is read: --evidence-id picks an exact `nd-` diagnostic (the id
the fleet report links); otherwise --file picks a name from an earlier
list; otherwise the newest file of --kind is read. --kind also narrows the
list.

Size: --tail limits lines (default {default}, max {max_lines}), and the relay
also limits the answer's size in bytes. The command only reads.

If the relay does not answer within --wait-seconds, the request stays
open. Run the same command again to read the answer; it joins the open
request instead of sending a second one.
""".format(
    default=EVIDENCE_TAIL_DEFAULT_LINES,
    max_lines=EVIDENCE_TAIL_MAX_LINES,
)


def _write_evidence(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    write_summary(
        "SESSION EVIDENCE",
        (
            ("SESSION", result.get("session_id")),
            ("MACHINE", result.get("machine_id")),
            ("FETCH JOB STATE", result.get("state")),
            ("RESULT", result.get("result_code")),
            ("FILES", len(result.get("files") or [])),
            ("SELECTED", result.get("selected_file")),
            ("BYTES", result.get("content_bytes")),
            ("TRUNCATED", bool(result.get("truncated"))),
            ("READ IT BACK", result.get("recovery")),
        ),
        stdout,
    )
    for entry in result.get("files") or []:
        stdout.write(
            f"  {entry.get('kind')}  {entry.get('name')}  "
            f"{entry.get('size_bytes')}B  {entry.get('modified_at')}\n"
        )
    content = result.get("content")
    if content:
        stdout.write(f"\n--- {result.get('selected_file')} ---\n{content}\n")


def session_evidence_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control evidence get",
        usage=EVIDENCE_GET_USAGE,
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--session",
        dest="target_session_id",
        required=True,
        metavar="SESSION-ID",
        help="Session whose files to read.",
    )
    parser.add_argument(
        "--kind",
        choices=EVIDENCE_KINDS,
        default=None,
        help="Kind of file to read; default: any kind.",
    )
    parser.add_argument(
        "--file",
        dest="file_name",
        default=None,
        metavar="NAME",
        help="File name from a previous listing.",
    )
    parser.add_argument(
        "--evidence-id",
        dest="evidence_id",
        default=None,
        metavar="ND-REF",
        help="Exact nd- diagnostic id to read.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=EVIDENCE_TAIL_DEFAULT_LINES,
        metavar="N",
        help=f"Lines to return (max {EVIDENCE_TAIL_MAX_LINES}).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=EVIDENCE_WAIT_DEFAULT_SECONDS,
        metavar="N",
        help=f"Seconds to wait for the session's relay (max {EVIDENCE_WAIT_MAX_SECONDS}).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EVIDENCE_GET_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {
        "session_id": parsed.target_session_id,
        "tail": parsed.tail,
        "wait_seconds": parsed.wait_seconds,
    }
    for name, value in (
        ("kind", parsed.kind),
        ("file", parsed.file_name),
        ("evidence_id", parsed.evidence_id),
    ):
        if value:
            payload[name] = value
    wait_seconds = min(max(parsed.wait_seconds, 0), EVIDENCE_WAIT_MAX_SECONDS)
    if wait_seconds:
        # The server holds this call open while the owning relay answers.
        announce_designed_wait(
            f"the relay owning session {parsed.target_session_id} to return evidence",
            max_wait_seconds=wait_seconds,
        )
    return dispatch_and_emit(
        function_id=EVIDENCE_GET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_evidence,
    )


__all__ = ["EVIDENCE_GET_USAGE", "session_evidence_get"]
