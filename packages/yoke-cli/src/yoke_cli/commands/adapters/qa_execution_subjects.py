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
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_cli.transport.test_machine_response_field import recorded_test_machine
from yoke_cli.commands.adapters.qa_catalog_usage import (
    USAGE_BY_FUNCTION_ID,
    PLAN_MATERIALIZE_EPILOG,
    PLAN_REMATERIALIZE_EPILOG,
)
from yoke_cli.qa_artifact_download import ArtifactDownloadError, download_artifact
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.qa_artifact_image_view import (
    ArtifactViewError,
    REGION_FORMAT,
    apply_artifact_view,
    parse_region,
    parse_scale,
    refuse_unsupported_content_type,
)
from yoke_contracts.qa_artifact_read import artifact_read_destination
from yoke_contracts.qa_requirement_replacement import (
    add_replaces_argument,
)


def qa_plan_materialize_for_item(args: List[str]) -> int:
    usage = USAGE_BY_FUNCTION_ID["qa.plan.materialize"]
    parser = argparse.ArgumentParser(
        prog="yoke qa plan materialize",
        usage=usage,
        epilog=PLAN_MATERIALIZE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument(
        "--item", metavar="PREFIX-N", help="Item whose QA cases to build."
    )
    subject.add_argument(
        "--deployment-run-id", metavar="RUN", help="Deployment run to build cases for."
    )
    parser.add_argument(
        "--transition", metavar="T", help="Workflow transition the cases block."
    )
    parser.add_argument("--plan", metavar="PLAN", help="QA plan to build cases from.")
    parser.add_argument(
        "--project", metavar="P", help="Project that owns the item or run."
    )
    parser.add_argument(
        "--stage",
        metavar="STAGE",
        help=(
            "Tie the cases to this pinned deployment QA stage. With --item, "
            "the cases are that item's deployment QA."
        ),
    )
    add_replaces_argument(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if parsed.item and parsed.stage and parsed.transition:
        return usage_error("item stage excludes a transition selector")
    if parsed.item and not (parsed.transition or parsed.stage):
        return usage_error("--item requires --transition or --stage")
    if parsed.item and parsed.plan and not parsed.stage:
        return usage_error("--item uses attached plans and does not accept --plan")
    if parsed.deployment_run_id and not parsed.plan and not parsed.stage:
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
    payload = {
        "transition_id": parsed.transition,
        "plan": parsed.plan,
        "project": parsed.project,
        "deployment_stage": parsed.stage,
    }
    if parsed.replaces:
        payload["replacements"] = parsed.replaces
    return dispatch_and_emit(
        function_id="qa.plan.materialize",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_plan_rematerialize(args: List[str]) -> int:
    usage = USAGE_BY_FUNCTION_ID["qa.plan.rematerialize"]
    parser = argparse.ArgumentParser(
        prog="yoke qa plan rematerialize",
        usage=usage,
        epilog=PLAN_REMATERIALIZE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument(
        "--item", metavar="PREFIX-N", help="Item whose QA cases to refresh."
    )
    subject.add_argument(
        "--deployment-run-id", metavar="RUN", help="Deployment run to refresh."
    )
    parser.add_argument(
        "--transition", metavar="T", help="Workflow transition the cases block."
    )
    parser.add_argument(
        "--project", metavar="P", help="Project that owns the item or run."
    )
    parser.add_argument(
        "--stage",
        metavar="STAGE",
        help="Pinned deployment QA stage whose cases to refresh.",
    )
    parser.add_argument(
        "--plan",
        metavar="PLAN",
        help="Refresh only cases built from this plan; needs --stage.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if parsed.item and parsed.plan and not parsed.stage:
        return usage_error(
            "item_plan_filter_unsupported: remove --plan; --item refreshes attached plans"
        )
    if parsed.item and parsed.stage and parsed.transition:
        return usage_error("item stage excludes a transition selector")
    if parsed.item and not (parsed.transition or parsed.stage):
        return usage_error("--item requires --transition or --stage")
    if parsed.deployment_run_id and not parsed.stage:
        return usage_error("--deployment-run-id requires --stage")
    if parsed.deployment_run_id and parsed.transition:
        return usage_error("--deployment-run-id does not accept --transition")
    target = (
        item_target("item", parsed.item, parsed.project)
        if parsed.item
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=parsed.deployment_run_id,
            project_id=parsed.project,
        )
    )
    payload = (
        {"transition_id": parsed.transition}
        if parsed.item and not parsed.stage
        else {
            "deployment_stage": parsed.stage,
            "plan": parsed.plan,
        }
    )
    return dispatch_and_emit(
        function_id="qa.plan.rematerialize",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_artifact_read(args: List[str]) -> int:
    usage = (
        "yoke qa artifact read --requirement-id N --artifact-id N "
        f"[--output PATH] [--region {REGION_FORMAT}] [--scale N] [--full] "
        "[--session-id S] [--json]"
    )
    parser = argparse.ArgumentParser(prog="yoke qa artifact read", usage=usage)
    for flag, text in (
        ("--requirement-id", "QA requirement id."),
        ("--artifact-id", "Artifact id."),
    ):
        parser.add_argument(flag, type=int, required=True, metavar="N", help=text)
    parser.add_argument(
        "--output",
        metavar="PATH",
        help=(
            "File to save the artifact to. Default: a new private folder "
            "under this machine's temp folder. That path changes on every "
            "read, so take it from the printed result instead of guessing it."
        ),
    )
    parser.add_argument(
        "--region",
        metavar=REGION_FORMAT,
        help=(
            "Save only this pixel rectangle of a screenshot, measured from "
            "its top-left corner. Use it to read one part of a long page. "
            "The stored artifact does not change; only the saved file does."
        ),
    )
    parser.add_argument(
        "--scale",
        metavar="N",
        help=(
            "Multiply the saved image's size, after --region. Use 0.5 to "
            "fit a tall capture on screen, or 2 to read small text."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        view_region = parse_region(parsed.region) if parsed.region else None
        view_scale = parse_scale(parsed.scale) if parsed.scale else None
    except ArtifactViewError as exc:
        return usage_error(f"yoke qa artifact read: {exc}", usage)
    return _artifact_read_to_path(
        parsed,
        region=view_region,
        scale=view_scale,
    )


def _artifact_read_to_path(
    parsed: Any,
    *,
    region: Any = None,
    scale: Any = None,
) -> int:
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
            print(_no_bytes_message(parsed, result), file=sys.stderr)
            return 1
        result["path"] = str(dest.resolve())
        # The file is the delivery. Inline bytes and the presigned download
        # URL are bearer material, so neither reaches the printed result.
        result.pop("content_base64", None)
        result.pop("download_url", None)
        if region is not None or scale is not None:
            try:
                refuse_unsupported_content_type(result.get("content_type"))
                result["artifact_view"] = apply_artifact_view(
                    dest,
                    region=region,
                    scale=scale,
                )
            except ArtifactViewError as exc:
                # The recorded bytes are already on disk, so the reader is
                # told where they are rather than losing the read along with
                # the view it asked for.
                print(
                    f"yoke qa artifact read: {exc} The bytes as recorded are "
                    f"at {dest.resolve()}.",
                    file=sys.stderr,
                )
                return 1
    return emit_response(response, json_mode=parsed.json_mode)


def _no_bytes_message(parsed, result: dict) -> str:
    """Name why no bytes landed, with the handler's detail and the recovery."""
    disposition = result.get("disposition") or "unknown"
    named = (result.get("detail"), recorded_test_machine(result))
    parts = [str(part) for part in named if part]
    detail = f"; {'; '.join(parts)}" if parts else ""
    if disposition == "evidence_missing":
        recovery = "Re-run the QA case to capture the evidence again."
    else:
        recovery = (
            "On the machine that captured it, run `yoke qa artifact rehome "
            f"--requirement-id {parsed.requirement_id} --artifact-id "
            f"{parsed.artifact_id}` to move the recorded bytes into the store "
            "the read surface serves; if the bytes are gone, re-run the case."
        )
    return (
        f"yoke qa artifact read: artifact {parsed.artifact_id} has no portable "
        f"bytes to land (disposition={disposition}{detail}). {recovery}"
    )


__all__ = [
    "qa_artifact_read",
    "qa_plan_materialize_for_item",
    "qa_plan_rematerialize",
]
