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
    "[--tail N] [--wait-seconds N] [--json]"
)
_DESCRIPTION = """Read one machine-local relay, watcher, or diagnostic file for a session.

Relay diagnostics, watcher captures, and the relay's own service logs live
only on the machine that produced them, so a seat elsewhere can see that a
launch or wake failed without seeing why. This asks that machine's relay,
over the same job routing that carries wakes and launch batches, for a
listing of what it holds for the session plus the tail of one file.

Selection, in order: --evidence-id names an exact `nd-` diagnostic (what the
fleet report links); --file names one entry from a previous listing; with
neither, the newest file of the requested --kind is read. --kind alone
narrows the listing.

Bounds: --tail caps lines (default {default}, max {max_lines}) and the relay
re-caps the answer in bytes whatever it was handed. The read never writes.

If the owning relay does not answer within --wait-seconds the request stays
pending and this same command reads it back — retrying joins the request in
flight rather than queueing a second one.
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
            ("STATE", result.get("state")),
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
    parser.add_argument("--session", dest="target_session_id", required=True)
    parser.add_argument("--kind", choices=EVIDENCE_KINDS, default=None)
    parser.add_argument("--file", dest="file_name", default=None)
    parser.add_argument("--evidence-id", dest="evidence_id", default=None)
    parser.add_argument(
        "--tail",
        type=int,
        default=EVIDENCE_TAIL_DEFAULT_LINES,
        help=f"lines to return (max {EVIDENCE_TAIL_MAX_LINES})",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=EVIDENCE_WAIT_DEFAULT_SECONDS,
        help=f"seconds to wait for the owning relay (max {EVIDENCE_WAIT_MAX_SECONDS})",
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
    return dispatch_and_emit(
        function_id=EVIDENCE_GET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_evidence,
    )


__all__ = ["EVIDENCE_GET_USAGE", "session_evidence_get"]
