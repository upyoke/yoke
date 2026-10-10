"""Publish full workflow definitions from a local JSON document."""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)

WORKFLOWS_VERSION_PUBLISH_USAGE = (
    "yoke workflows version publish WORKFLOW --definition-file F --reason TEXT "
    "[--expected-current-version N] [--keep-current] [--session-id S] [--json]"
)


def workflows_version_publish(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows version publish",
        description="Publish a validated immutable definition. Existing workflows require --expected-current-version. "
        "--keep-current appends without changing the default or canon-follow. New workflows omit the expected version "
        "and select their first version. Existing item pins remain unchanged; use workflows item migrate explicitly.",
        epilog="Read the current definition with yoke workflows version get WORKFLOW VERSION --json, "
        "edit its definition object, then publish it with an audit reason.",
    )
    parser.add_argument("workflow")
    parser.add_argument("--definition-file", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--expected-current-version", type=int)
    parser.add_argument("--keep-current", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_VERSION_PUBLISH_USAGE)
    if parsed is None:
        return 2
    try:
        definition = json.loads(Path(parsed.definition_file).read_text())
        if not isinstance(definition, dict):
            raise ValueError("definition must be a JSON object")
    except (OSError, ValueError) as exc:
        print(
            f"workflow_definition_file_invalid: {exc}; supply a readable JSON definition object",
            file=sys.stderr,
        )
        return 2
    return dispatch_and_emit(
        function_id="workflows.version.publish",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": parsed.workflow,
            "definition": definition,
            "reason": parsed.reason,
            "expected_current_version": parsed.expected_current_version,
            "keep_current": parsed.keep_current,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
