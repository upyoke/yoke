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
from yoke_cli.qa_artifact_download import ArtifactDownloadError, download_artifact
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.qa_artifact_read import artifact_read_destination


def qa_plan_materialize_for_item(args: List[str]) -> int:
    usage = (
        "yoke qa plan materialize "
        "(--item PREFIX-N --transition T | "
        "--deployment-run-id RUN --plan PLAN --project P "
        "[--stage STAGE [--member PREFIX-N]]) [--json]"
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
    parser.add_argument(
        "--stage",
        help=(
            "Bind the materialized cases to a pinned deployment QA stage. "
            "An item-scoped stage also requires --member."
        ),
    )
    parser.add_argument(
        "--member",
        help="The run member item an item-scoped QA stage credits.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if parsed.item and not parsed.transition:
        return usage_error("--item requires --transition")
    if parsed.item and parsed.plan:
        return usage_error("--item uses attached plans and does not accept --plan")
    if parsed.deployment_run_id and not parsed.plan and not parsed.stage:
        return usage_error("--deployment-run-id requires --plan")
    if parsed.member and not parsed.stage:
        return usage_error("--member requires --stage")
    if parsed.stage and not parsed.deployment_run_id:
        return usage_error("--stage belongs to --deployment-run-id materialization")
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
            "deployment_stage": parsed.stage,
            "deployment_member": parsed.member,
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
    parser.add_argument(
        "--output",
        help=(
            "Where to land the evidence bytes. Defaults to a fresh private "
            "directory under this machine's temp root, so a reviewer can "
            "open the file without choosing a destination its own path "
            "guard would refuse. The destination differs on every read -- "
            "read it back from the reported path rather than composing it."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return _artifact_read_to_path(parsed)


def _artifact_read_to_path(parsed: Any) -> int:
    """Dispatch the read, then land the bytes where the caller can open them."""
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
    result = response.result if response.success else None
    if isinstance(result, dict):
        dest = (
            Path(parsed.output).expanduser()
            if parsed.output
            else artifact_read_destination(
                parsed.artifact_id,
                content_type=result.get("content_type"),
            )
        )
        encoded = result.get("content_base64")
        source = result.get("path")
        if encoded:
            dest.write_bytes(base64.b64decode(encoded))
        elif source and Path(str(source)).is_file():
            shutil.copyfile(str(source), dest)
        elif result.get("download_url"):
            try:
                download_artifact(str(result["download_url"]), dest)
            except ArtifactDownloadError as exc:
                print(f"yoke qa artifact read: {exc}", file=sys.stderr)
                return 1
        else:
            print(
                "yoke qa artifact read: artifact "
                f"{parsed.artifact_id} has no portable bytes to land "
                f"(disposition={result.get('disposition') or 'unknown'}"
                f"{_disposition_detail(result)}). Re-run the case on the "
                "machine holding the evidence, or record the bytes with "
                "`yoke qa artifact add --content-file PATH` so the read "
                "surface can serve them.",
                file=sys.stderr,
            )
            return 1
        result["path"] = str(dest.resolve())
        # The file IS the delivery, so the inline copy would only make the
        # reader page a base64 blob to reach the path that already holds it.
        result.pop("content_base64", None)
    return emit_response(response, json_mode=parsed.json_mode)


def _disposition_detail(result: dict) -> str:
    """Render the read handler's own explanation when it gave one."""
    detail = result.get("detail")
    machine = result.get("machine")
    parts = [str(part) for part in (detail, machine) if part]
    return f"; {'; '.join(parts)}" if parts else ""


__all__ = [
    "qa_artifact_read",
    "qa_plan_materialize_for_item",
    "qa_plan_rematerialize",
]
