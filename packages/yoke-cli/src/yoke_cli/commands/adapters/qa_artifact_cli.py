"""CLI adapters for ``qa.artifact.add`` and ``qa.artifact.presign``."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


QA_ARTIFACT_ADD_USAGE = (
    "yoke qa artifact add --requirement-id N --run-id N "
    "--artifact-type TYPE (--artifact-handle JSON | "
    "--content-base64 B64 --filename NAME | --content-file PATH) "
    "[--content-type CT] [--metadata JSON] [--session-id S] [--json]"
)


def qa_artifact_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa artifact add",
        usage=QA_ARTIFACT_ADD_USAGE,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id the run belongs to.",
    )
    parser.add_argument(
        "--run-id", dest="run_id", type=int, required=True, metavar="N",
        help="Id of the QA run to attach the file to.",
    )
    parser.add_argument(
        "--artifact-type",
        dest="artifact_type",
        required=True,
        metavar="TYPE",
        help="Kind of evidence, e.g. screenshot.",
    )
    parser.add_argument(
        "--content-type",
        dest="content_type",
        default=None,
        metavar="CT",
        help="MIME content type, e.g. image/png.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--artifact-handle",
        dest="artifact_handle",
        default=None,
        metavar="JSON",
        help=(
            "Typed handle JSON naming where the evidence lives: "
            '{"backend":"s3","bucket":B,"key":K} for uploaded '
            'evidence, {"backend":"local","path":P} for explicit '
            "machine-local evidence. Bare paths are refused, and so is a "
            "local handle on a mission capture run that the control plane "
            "cannot read — send those bytes with --content-file instead. "
            "Mutually exclusive with --content-base64 / --content-file."
        ),
    )
    source.add_argument(
        "--content-base64",
        dest="content_base64",
        default=None,
        metavar="B64",
        help="Evidence bytes, base64-encoded. Requires --filename.",
    )
    source.add_argument(
        "--content-file",
        dest="content_file",
        default=None,
        metavar="PATH",
        help="Read this local file and upload its bytes.",
    )
    parser.add_argument(
        "--filename",
        default=None,
        metavar="NAME",
        help="File name with no directory part. Required with --content-base64; "
        "with --content-file it defaults to that file's name.",
    )
    parser.add_argument(
        "--metadata", default=None, metavar="JSON", help="Extra metadata as a JSON string."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_ADD_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "run_id": int(parsed.run_id),
        "artifact_type": parsed.artifact_type,
    }
    if parsed.artifact_handle is not None:
        try:
            payload["artifact_handle"] = json.loads(parsed.artifact_handle)
        except json.JSONDecodeError as exc:
            print(
                f"yoke qa artifact add: --artifact-handle is not valid JSON "
                f"({exc}); pass a typed handle object, not a bare path.",
            )
            return 2
    elif parsed.content_file is not None:
        path = Path(parsed.content_file)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            print(f"yoke qa artifact add: cannot read --content-file: {exc}")
            return 2
        payload["content_base64"] = base64.b64encode(raw).decode("ascii")
        payload["filename"] = parsed.filename or path.name
    else:
        payload["content_base64"] = parsed.content_base64
        if parsed.filename is not None:
            payload["filename"] = parsed.filename
    for key in ("content_type", "metadata"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    return dispatch_and_emit(
        function_id="qa.artifact.add",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_ARTIFACT_PRESIGN_USAGE = (
    "yoke qa artifact presign --requirement-id N --run-id N "
    "--filename NAME [--content-type CT] [--full] [--session-id S] [--json]"
)


def qa_artifact_presign(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa artifact presign",
        usage=QA_ARTIFACT_PRESIGN_USAGE,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id the run belongs to.",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        type=int,
        required=True,
        metavar="N",
        help="Id of the QA run the upload belongs to; it names the S3 key.",
    )
    parser.add_argument(
        "--filename",
        required=True,
        metavar="NAME",
        help="File name for the upload, with no directory part.",
    )
    parser.add_argument(
        "--content-type",
        dest="content_type",
        default=None,
        metavar="CT",
        help="MIME content type for the upload, e.g. image/png.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_PRESIGN_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "run_id": int(parsed.run_id),
        "filename": parsed.filename,
    }
    if parsed.content_type is not None:
        payload["content_type"] = parsed.content_type
    return dispatch_and_emit(
        function_id="qa.artifact.presign",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_ARTIFACT_ADD_USAGE",
    "QA_ARTIFACT_PRESIGN_USAGE",
    "qa_artifact_add",
    "qa_artifact_presign",
]
