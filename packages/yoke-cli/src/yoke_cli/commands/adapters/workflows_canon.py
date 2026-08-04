"""CLI adapters for the published canon and for taking an update from it."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


WORKFLOWS_CANON_GET_USAGE = (
    "yoke workflows canon get WORKFLOW [--canon-version N] "
    "[--session-id S] [--json]"
)
WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE = (
    "yoke workflows canon-update preview WORKFLOW [--session-id S] [--json]"
)
WORKFLOWS_CANON_UPDATE_APPLY_USAGE = (
    "yoke workflows canon-update apply WORKFLOW "
    "--expected-current-version N [--session-id S] [--json]"
)


def workflows_canon_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows canon get",
        description=WORKFLOWS_CANON_GET_USAGE,
    )
    parser.add_argument("workflow")
    parser.add_argument("--canon-version", type=int, default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WORKFLOWS_CANON_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"workflow-canon|{result.get('workflow_id') or ''}|"
            f"{result.get('canon_version') or ''}|"
            f"{'newest' if result.get('is_newest') else 'superseded'}|"
            f"{(result.get('definition_digest') or '')[:12]}",
            file=stdout,
        )

    payload = {"workflow_id": parsed.workflow}
    if parsed.canon_version is not None:
        payload["canon_version"] = parsed.canon_version
    return dispatch_and_emit(
        function_id="workflows.canon.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        as_json=parsed.json,
        human_writer=_human_writer,
    )


def workflows_canon_update_preview(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows canon-update preview",
        description=WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE,
    )
    parser.add_argument("workflow")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        conflicts = [row.get("path") for row in result.get("conflicts") or []]
        # Conflicts first: they are the only outcome that needs a decision.
        print(
            f"workflow-canon-update|{result.get('workflow_id') or ''}|"
            f"{result.get('state') or ''}|"
            f"{'clean' if result.get('clean') else 'conflicted'}|"
            f"takes={len(result.get('taken') or [])}|"
            f"keeps={len(result.get('kept') or [])}",
            file=stdout,
        )
        for path in conflicts:
            print(f"  conflict: {path}", file=stdout)

    return dispatch_and_emit(
        function_id="workflows.canon_update.preview",
        target=TargetRef(kind="global"),
        payload={"workflow_id": parsed.workflow},
        session_id=parsed.session_id,
        as_json=parsed.json,
        human_writer=_human_writer,
    )


def workflows_canon_update_apply(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows canon-update apply",
        description=WORKFLOWS_CANON_UPDATE_APPLY_USAGE,
    )
    parser.add_argument("workflow")
    parser.add_argument("--expected-current-version", type=int, required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_UPDATE_APPLY_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"workflow-canon-applied|{result.get('workflow_id') or ''}|"
            f"{result.get('version') or ''}|"
            f"{result.get('version_id') or ''}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="workflows.canon_update.apply",
        target=TargetRef(kind="global"),
        payload={
            "workflow_id": parsed.workflow,
            "expected_current_version": parsed.expected_current_version,
        },
        session_id=parsed.session_id,
        as_json=parsed.json,
        human_writer=_human_writer,
    )


__all__ = [
    "WORKFLOWS_CANON_GET_USAGE",
    "WORKFLOWS_CANON_UPDATE_APPLY_USAGE",
    "WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE",
    "workflows_canon_get",
    "workflows_canon_update_apply",
    "workflows_canon_update_preview",
]
