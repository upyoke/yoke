"""Flag adapters for QA materialization and artifact subject operations."""

from __future__ import annotations

import argparse
import base64
import shutil
import sys
from pathlib import Path
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)
from yoke_contracts.api.function_call import TargetRef


def qa_plan_materialize_for_item(args: List[str]) -> int:
    usage = (
        "yoke qa plan materialize "
        "(--item PREFIX-N --transition T | "
        "--deployment-run-id RUN --plan PLAN --project P) [--json]"
    )
    parser = argparse.ArgumentParser(
        prog="yoke qa plan materialize",
        description=usage,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--transition")
    parser.add_argument("--plan")
    parser.add_argument("--project")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if parsed.item and not parsed.transition:
        return usage_error("--item requires --transition")
    if parsed.item and parsed.plan:
        return usage_error("--item uses attached plans and does not accept --plan")
    if parsed.deployment_run_id and not parsed.plan:
        return usage_error("--deployment-run-id requires --plan")
    if parsed.deployment_run_id and parsed.transition:
        return usage_error("--deployment-run-id does not accept --transition")
    if parsed.deployment_run_id and not parsed.project:
        return usage_error("--deployment-run-id requires --project")
    target = (
        item_target("item", parsed.item, parsed.project)
        if parsed.item
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=parsed.deployment_run_id,
            project_id=parsed.project,
        )
    )
    return dispatch_and_emit(
        function_id="qa.plan.materialize",
        target=target,
        payload={
            "transition_id": parsed.transition,
            "plan": parsed.plan,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_plan_rematerialize(args: List[str]) -> int:
    usage = "yoke qa plan rematerialize --item PREFIX-N --transition T [--json]"
    parser = argparse.ArgumentParser(
        prog="yoke qa plan rematerialize",
        description=usage,
    )
    parser.add_argument("--item", required=True)
    parser.add_argument("--transition", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.plan.rematerialize",
        target=item_target("item", parsed.item, parsed.project),
        payload={"transition_id": parsed.transition},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_artifact_read(args: List[str]) -> int:
    usage = (
        "yoke qa artifact read --requirement-id N --artifact-id N "
        "[--output PATH] [--json]"
    )
    parser = argparse.ArgumentParser(
        prog="yoke qa artifact read",
        description=usage,
    )
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--output")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if not parsed.output:
        return dispatch_and_emit(
            function_id="qa.artifact.read",
            target=TargetRef(
                kind="qa_requirement",
                qa_requirement_id=parsed.requirement_id,
            ),
            payload={"artifact_id": parsed.artifact_id},
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    return _artifact_read_to_path(parsed)


def _artifact_read_to_path(parsed: Any) -> int:
    """Dispatch the read, then land bytes at ``--output`` when present."""
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="qa.artifact.read",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=parsed.requirement_id,
        ),
        payload={"artifact_id": parsed.artifact_id},
        actor=build_actor(session_id=parsed.session_id),
    )
    dest = Path(parsed.output).expanduser()
    result = response.result if response.success else None
    if isinstance(result, dict):
        encoded = result.get("content_base64")
        source = result.get("path")
        if encoded:
            dest.write_bytes(base64.b64decode(encoded))
        elif source and Path(str(source)).is_file():
            shutil.copyfile(str(source), dest)
        else:
            print(
                "yoke qa artifact read: no portable bytes to write to --output",
                file=sys.stderr,
            )
            return emit_response(response, json_mode=parsed.json_mode)
        result["path"] = str(dest.resolve())
    return emit_response(response, json_mode=parsed.json_mode)


__all__ = [
    "qa_artifact_read",
    "qa_plan_materialize_for_item",
    "qa_plan_rematerialize",
]
