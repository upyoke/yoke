"""CLI adapter for ``qa.artifact.rehome``.

Runs on the machine that captured the evidence: it reads each artifact's
recorded local file and hands the bytes to the build serving the universe,
which stores them and swaps the handle on the same artifact row. A database
door relays the write to its https plane (see
:mod:`yoke_contracts.qa_evidence_plane`), so the bytes land in the store a
hosted reviewer reads, not back on this disk.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import TargetRef

QA_ARTIFACT_REHOME_USAGE = (
    "yoke qa artifact rehome --requirement-id N --artifact-id N "
    "[--artifact-id N ...] [--session-id S] [--json]"
)

_PROG = "yoke qa artifact rehome"


def _recorded_source(result: dict[str, Any]) -> str | None:
    """The capture machine's recorded file, whichever read answered."""
    return result.get("recorded_path") or result.get("path")


def _rehome_one(parsed: Any, artifact_id: int) -> tuple[int, Any]:
    target = TargetRef(kind="qa_requirement", qa_requirement_id=parsed.requirement_id)
    actor = build_actor(session_id=parsed.session_id)
    read = call_dispatcher(
        function_id="qa.artifact.read",
        target=target,
        payload={"artifact_id": artifact_id},
        actor=actor,
    )
    if not read.success:
        return 1, read
    result = read.result or {}
    if result.get("backend") != "local":
        print(f"{_PROG}: artifact {artifact_id} is already in the object store")
        return 0, None
    source = _recorded_source(result)
    if not source:
        print(
            f"{_PROG}: artifact {artifact_id} is local, but the serving build "
            "did not report where it was recorded; that build is older than "
            "this recovery. Re-run once it serves qa.artifact.rehome.",
            file=sys.stderr,
        )
        return 1, None
    try:
        source_bytes = Path(str(source)).read_bytes()
    except OSError as exc:
        machine = result.get("machine")
        where = f" on {machine}" if machine else " on the machine that captured it"
        print(
            f"{_PROG}: artifact {artifact_id} was recorded at {source}, which "
            f"cannot be read here ({exc}). Run this recovery{where}; if the "
            "bytes are gone, re-run the capture through the https connection "
            "that serves the universe.",
            file=sys.stderr,
        )
        return 1, None
    response = call_dispatcher(
        function_id="qa.artifact.rehome",
        target=target,
        payload={
            "artifact_id": artifact_id,
            "content_base64": base64.b64encode(source_bytes).decode("ascii"),
        },
        actor=actor,
    )
    return (0 if response.success else 1), response


def qa_artifact_rehome(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog=_PROG, description=QA_ARTIFACT_REHOME_USAGE)
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="The requirement whose run captured the artifacts.",
    )
    parser.add_argument(
        "--artifact-id",
        dest="artifact_ids",
        type=int,
        action="append",
        required=True,
        help="A qa_artifacts.id to move into the serving build's store; repeat.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_REHOME_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    status = 0
    for artifact_id in parsed.artifact_ids:
        code, response = _rehome_one(parsed, artifact_id)
        if response is not None:
            emit_response(response, json_mode=parsed.json_mode)
        if code:
            status = code
            break
    return status


__all__ = ["QA_ARTIFACT_REHOME_USAGE", "qa_artifact_rehome"]
