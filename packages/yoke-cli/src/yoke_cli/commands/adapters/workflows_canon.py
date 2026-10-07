"""CLI adapters for following and taking published workflow updates.

A built-in workflow's definitions are published by Yoke as canon generations.
These commands list where each workflow stands, preview the merge a take would
produce, take one or several updates, and choose whether the next generation
arrives by itself.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.workflows_canon_help import (
    APPLY_ALL_DESCRIPTION,
    APPLY_DESCRIPTION,
    CANON_STATUS_LIST_DESCRIPTION,
    FOLLOW_DESCRIPTION,
    PREVIEW_DESCRIPTION,
    WORKFLOWS_CANON_FOLLOW_SET_USAGE,
    WORKFLOWS_CANON_STATUS_LIST_USAGE,
    WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE,
    WORKFLOWS_CANON_UPDATE_APPLY_USAGE,
    WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE,
)
from yoke_contracts.api.function_call import TargetRef



def _parser(prog: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=prog,
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _dispatch(function_id: str, payload: Dict[str, Any], parsed, writer,
              **extra: Any) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
        **extra,
    )


def _print_paths(stdout, workflow_id: str, result: Dict[str, Any]) -> None:
    for label in ("taken", "kept"):
        for path in result.get(label) or []:
            print(f"{label}|{workflow_id}|{path}", file=stdout)


def _print_applied(stdout, row: Dict[str, Any], from_version: Any) -> None:
    workflow_id = row.get("workflow_id") or ""
    print(
        f"workflow-canon-update-applied|{workflow_id}|"
        f"from_version={from_version}|to_version={row.get('version') or ''}|"
        f"canon_version={row.get('canon_version') or ''}|"
        f"{row.get('definition_digest') or ''}",
        file=stdout,
    )
    _print_paths(stdout, workflow_id, row)


def workflows_canon_status_list(args: List[str]) -> int:
    parser = _parser("yoke workflows canon-status list",
                     CANON_STATUS_LIST_DESCRIPTION)
    parser.add_argument("--pending", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_STATUS_LIST_USAGE
    )
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        del stderr
        rows = (response.result or {}).get("rows") or []
        if not rows:
            print(
                "no workflow has a pending published update"
                if parsed.pending else "no workflow has a published canon",
                file=stdout,
            )
        for row in rows:
            print(
                "|".join(str(value) for value in (
                    "workflow-canon",
                    row.get("workflow_id", ""),
                    f"current_version={row.get('current_version', '')}",
                    row.get("state", ""),
                    f"follow={row.get('follow', '')}",
                    f"latest_canon_version={row.get('latest_canon_version', '')}",
                    f"pending={str(bool(row.get('pending'))).lower()}",
                )),
                file=stdout,
            )

    return _dispatch(
        "workflows.canon_status.list",
        {"pending_only": True} if parsed.pending else {},
        parsed,
        _writer,
    )


def workflows_canon_update_preview(args: List[str]) -> int:
    parser = _parser("yoke workflows canon-update preview", PREVIEW_DESCRIPTION)
    parser.add_argument("workflow")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_UPDATE_PREVIEW_USAGE
    )
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        result = response.result or {}
        workflow_id = result.get("workflow_id") or parsed.workflow
        derived = result.get("derived_from_canon_version")
        print(
            f"workflow-canon-preview|{workflow_id}|{result.get('state') or ''}|"
            f"derived_from_canon_version={'' if derived is None else derived}|"
            f"latest_canon_version={result.get('latest_canon_version') or ''}|"
            f"clean={str(bool(result.get('clean'))).lower()}",
            file=stdout,
        )
        _print_paths(stdout, workflow_id, result)
        conflicts = result.get("conflicts") or []
        for conflict in conflicts:
            print(f"conflict|{workflow_id}|{conflict.get('path', '')}",
                  file=stdout)
        if conflicts:
            print(
                "this update conflicts with local edits and will refuse to "
                "apply; edit the workflow to resolve each conflict, then "
                "publish",
                file=stderr,
            )

    return _dispatch(
        "workflows.canon_update.preview",
        {"workflow_id": parsed.workflow},
        parsed,
        _writer,
    )


def workflows_canon_update_apply(args: List[str]) -> int:
    parser = _parser("yoke workflows canon-update apply", APPLY_DESCRIPTION)
    parser.add_argument("workflow")
    parser.add_argument("--expected-current-version", type=int, required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_UPDATE_APPLY_USAGE
    )
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        del stderr
        _print_applied(
            stdout, response.result or {}, parsed.expected_current_version
        )

    return _dispatch(
        "workflows.canon_update.apply",
        {
            "workflow_id": parsed.workflow,
            "expected_current_version": parsed.expected_current_version,
        },
        parsed,
        _writer,
    )


def _apply_all_entries(raw: List[str]) -> List[Dict[str, Any]] | str:
    entries: List[Dict[str, Any]] = []
    for token in raw:
        workflow_id, sep, version = token.partition("=")
        if not sep or not workflow_id or not version.isdigit():
            return (
                f"expected WORKFLOW=VERSION, got {token!r}; read each "
                "workflow's current_version from "
                "`yoke workflows canon-status list --pending`"
            )
        entries.append({
            "workflow_id": workflow_id,
            "expected_current_version": int(version),
        })
    return entries


def workflows_canon_update_apply_all(args: List[str]) -> int:
    parser = _parser("yoke workflows canon-update apply-all",
                     APPLY_ALL_DESCRIPTION)
    parser.add_argument("entries", nargs="+", metavar="WORKFLOW=VERSION")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_UPDATE_APPLY_ALL_USAGE
    )
    if parsed is None:
        return 2
    entries = _apply_all_entries(parsed.entries)
    if isinstance(entries, str):
        return usage_error(entries)
    expected = {
        entry["workflow_id"]: entry["expected_current_version"]
        for entry in entries
    }
    refused: List[Dict[str, Any]] = []

    def _note_refusals(response, actor):
        del actor
        if response.success:
            refused.extend((response.result or {}).get("refused") or [])
        return response

    def _writer(response, stdout, stderr) -> None:
        result = response.result or {}
        for row in result.get("applied") or []:
            _print_applied(stdout, row, expected.get(row.get("workflow_id")))
        for row in result.get("refused") or []:
            print(
                f"workflow-canon-update-refused|{row.get('workflow_id', '')}|"
                f"{row.get('code', '')}|{row.get('message', '')}",
                file=stdout,
            )
            print(
                f"inspect: yoke workflows canon-update preview "
                f"{row.get('workflow_id', '')}",
                file=stderr,
            )

    rc = _dispatch(
        "workflows.canon_update.apply_all",
        {"workflows": entries},
        parsed,
        _writer,
        response_recovery=_note_refusals,
    )
    if rc == 0 and refused:
        print(
            f"{len(refused)} of {len(entries)} workflow update(s) refused",
            file=sys.stderr,
        )
        return 1
    return rc


def workflows_canon_follow_set(args: List[str]) -> int:
    parser = _parser("yoke workflows canon-follow set", FOLLOW_DESCRIPTION)
    parser.add_argument("workflow")
    parser.add_argument("follow", choices=("auto", "manual"))
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_CANON_FOLLOW_SET_USAGE
    )
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        previous = result.get("previous_follow")
        print(
            f"workflow-canon-follow|{result.get('workflow_id') or ''}|"
            + (f"{previous}->" if previous else "")
            + f"{result.get('follow') or ''}",
            file=stdout,
        )

    return _dispatch(
        "workflows.canon_follow.set",
        {"workflow_id": parsed.workflow, "follow": parsed.follow},
        parsed,
        _writer,
    )


__all__ = [
    "workflows_canon_follow_set",
    "workflows_canon_status_list",
    "workflows_canon_update_apply",
    "workflows_canon_update_apply_all",
    "workflows_canon_update_preview",
]
