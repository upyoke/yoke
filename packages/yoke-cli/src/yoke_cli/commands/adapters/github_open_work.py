"""Adapter for listing a project's open GitHub issues and pull requests."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


GITHUB_OPEN_WORK_LIST_USAGE = (
    "yoke github open-work list --project P [--limit N] [--full] "
    "[--session-id S] [--json]"
)

#: Rows per list in the human reply; --json carries every row.
HUMAN_ROWS_PER_LIST = 15


def _issue_line(row: Dict[str, Any]) -> str:
    labels = ", ".join(row.get("labels") or [])
    suffix = f" [{labels}]" if labels else ""
    return f"  #{row.get('number')} {row.get('title')}{suffix}"


def _pull_line(row: Dict[str, Any]) -> str:
    draft = " (draft)" if row.get("draft") else ""
    return f"  #{row.get('number')} {row.get('title')}{draft} <- {row.get('head_ref')}"


def _write_section(stdout, label: str, rows: List[Dict[str, Any]], line) -> None:
    print(f"Open {label}: {len(rows)}", file=stdout)
    for row in rows[:HUMAN_ROWS_PER_LIST]:
        print(line(row), file=stdout)
    hidden = len(rows) - HUMAN_ROWS_PER_LIST
    if hidden > 0:
        print(f"  ... {hidden} more; --json lists every row", file=stdout)


def _write_open_work(response, stdout, stderr) -> None:
    del stderr
    result = response.result or {}
    print(f"Repository: {result.get('repo')}", file=stdout)
    _write_section(stdout, "issues", result.get("issues") or [], _issue_line)
    _write_section(
        stdout, "pull requests", result.get("pull_requests") or [], _pull_line
    )
    if result.get("truncated"):
        print(
            "More open work exists than this reply carries; raise --limit "
            "or browse the repository.",
            file=stdout,
        )


def github_open_work_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github open-work list",
        description=(
            "List the open issues and open pull requests of the project's bound "
            "GitHub repository, newest-updated first, through the project's "
            "GitHub binding; no host GitHub CLI is needed. The human reply shows "
            "counts and the first rows of each list; --json carries every row."
        ),
    )
    parser.add_argument(
        "--project", required=True, help="Project whose repository to read."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Rows per list; the server defaults to 100 and allows at most 200.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Permit a --json reply larger than the CLI read output limit.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_OPEN_WORK_LIST_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="github.open_work.list",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            **({"limit": parsed.limit} if parsed.limit is not None else {}),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_open_work,
    )


__all__ = ["GITHUB_OPEN_WORK_LIST_USAGE", "github_open_work_list"]
