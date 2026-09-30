"""CLI read for QA artifact metadata without evidence download."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import add_json_arg, add_session_arg, dispatch_and_emit, parse_or_usage_error, usage_error
from yoke_contracts.api.function_call import TargetRef


QA_ARTIFACT_GET_USAGE = (
    "yoke qa artifact get ARTIFACT_ID --requirement-id N [--json] "
    "(metadata only; use `yoke qa artifact read` for evidence)"
)


def qa_artifact_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke qa artifact get", description=QA_ARTIFACT_GET_USAGE)
    parser.add_argument("artifact", nargs="?", type=int)
    parser.add_argument("--artifact-id", type=int)
    parser.add_argument("--requirement-id", required=True, type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_GET_USAGE)
    if parsed is None:
        return 2
    if (parsed.artifact is None) == (parsed.artifact_id is None):
        return usage_error("provide exactly one artifact id, positionally or with --artifact-id")
    artifact_id = parsed.artifact if parsed.artifact is not None else parsed.artifact_id
    return dispatch_and_emit(
        function_id="qa.artifact.get",
        target=TargetRef(kind="qa_requirement", qa_requirement_id=parsed.requirement_id),
        payload={"artifact_id": artifact_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = ["QA_ARTIFACT_GET_USAGE", "qa_artifact_get"]
