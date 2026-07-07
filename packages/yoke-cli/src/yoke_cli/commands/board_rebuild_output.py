"""Output helpers for the ``yoke board rebuild`` CLI adapter.

Import-isolated: the result type, status constants, and board-path resolution
all come from the client-tier :mod:`yoke_cli.board` modules, so formatting a
rebuild result never loads engine (``yoke_core``) code.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

from yoke_cli.terminal_pager import page_or_write
from yoke_cli.commands.board_terminal_output import (
    board_print_content,
    simplify_board_text,
    source_banner,
    terminal_needs_plain_board,
)
from yoke_cli.board import outcome as _outcome
from yoke_cli.board.outcome import REBUILT, FAILED, PRINTED, RebuildResult
from yoke_cli.board.rebuild import resolve_board_path
from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_contracts.api.function_call import FunctionError


def write_board_rebuild_human(response, stdout, _stderr) -> None:
    result = response.result or {}
    targets = result.get("targets") or []
    rows = targets or [result]
    for row in rows:
        status = row.get("status") or result.get("status") or "unknown"
        path = row.get("board_path") or result.get("board_path") or "BOARD.md"
        if status == REBUILT:
            print(f"Board rebuilt: {path}", file=stdout)
        elif status == PRINTED:
            print(f"Board rendered: {path}", file=stdout)
        elif status == "throttled":
            print(f"Board rebuild throttled: {path}", file=stdout)
        else:
            print(f"Board rebuild {status}: {path}", file=stdout)


def coerce_rebuild_outcome(result: object) -> RebuildResult:
    # Accept the CLI-tier RebuildResult (or any duck-typed outcome carrying
    # status/exit_code/board_path, e.g. the source-dev RebuildOutcome) as-is.
    if hasattr(result, "exit_code") and hasattr(result, "status"):
        return result  # type: ignore[return-value]
    if isinstance(result, int):
        status = REBUILT if result == 0 else FAILED
        return _outcome.RebuildResult(status, int(result))
    raise TypeError(f"rebuild returned unsupported result {type(result)!r}")


def result_board_path(
    result: RebuildResult, repo_root: Path, output_name: str | None,
) -> Path:
    if result.board_path:
        return Path(result.board_path)
    return resolve_board_path(repo_root, output_name)


def read_board_text(
    result: RebuildResult,
    *,
    repo_root: Path,
    output_name: str | None,
) -> str:
    board_path = result_board_path(result, repo_root, output_name)
    if not board_path.is_file():
        return ""
    return board_path.read_text(encoding="utf-8")


def _content_stats(content: str) -> tuple[str, int]:
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
    line_count = content.count("\n") + (
        0 if content.endswith("\n") or not content else 1
    )
    return sha, line_count


def board_payload(
    result: RebuildResult,
    *,
    repo_root: Path,
    output_name: str | None,
    content: str | None = None,
    scope: str | None = None,
    env_name: str | None = None,
    data_source: str | None = None,
) -> Dict[str, Any]:
    board_path = result_board_path(result, repo_root, output_name)
    if content is None:
        content = read_board_text(result, repo_root=repo_root, output_name=output_name)
    sha, line_count = _content_stats(content)
    return {
        "board_path": str(board_path),
        "repo_root": str(repo_root),
        "scope": str(scope or ""),
        "env_name": str(env_name or ""),
        "data_source": str(data_source or ""),
        "status": result.status,
        "changed": result.changed,
        "message": result.message,
        "targets": [
            {
                "board_path": child.board_path,
                "status": child.status,
                "changed": child.changed,
                "exit_code": child.exit_code,
                "message": child.message,
            }
            for child in result.children
        ],
        "sha256": sha,
        "line_count": line_count,
        "exit_code": int(result.exit_code),
    }


def _board_error(result: RebuildResult) -> FunctionError | None:
    if result.exit_code == 0:
        return None
    message = f"rebuild_board exited with {result.exit_code} status={result.status}"
    if result.message:
        message = f"{message}: {result.message}"
    return FunctionError(code="downstream_failure", message=message)


def emit_board_json(
    result: RebuildResult,
    payload: Dict[str, Any],
    *,
    event_ids: list[str] | None = None,
) -> None:
    error = _board_error(result)
    envelope = {
        "success": result.exit_code == 0,
        "function": "board.rebuild.run",
        "version": "v1",
        "request_id": None,
        "result": payload,
        "warnings": [],
        "error": error.model_dump(mode="json") if error else None,
        "event_ids": list(event_ids or []),
    }
    print(json.dumps(envelope, sort_keys=True))


def emit_board_human(result: RebuildResult, payload: Dict[str, Any]) -> None:
    if result.exit_code == 0:
        class _Response:
            def __init__(self, result):
                self.result = result

        write_board_rebuild_human(
            _Response(payload), stdout=sys.stdout, _stderr=sys.stderr,
        )
        return

    rows = result.children if result.children else (result,)
    for row in rows:
        message = row.message or f"Board rebuild {row.status}: {row.board_path}"
        stream = (
            sys.stderr
            if row.status in {_outcome.FAILED, _outcome.LOCK_SKIPPED}
            else sys.stdout
        )
        print(message, file=stream)
    print(f"hint: {_FIELD_NOTE_FOOTER}", file=sys.stderr)


def emit_board_print(
    result: RebuildResult,
    payload: Dict[str, Any],
    content: str,
    *,
    no_pager: bool = False,
) -> None:
    output = board_print_content(content, payload)
    # Page the board like git when stdout is a TTY (interactive operator);
    # pipes, redirects, and agent/automation calls write straight through.
    # The status line below still lands on stderr, after the pager exits.
    page_or_write(output, enabled=not no_pager)
    if result.exit_code == 0:
        class _Response:
            def __init__(self, result):
                self.result = result

        write_board_rebuild_human(
            _Response(payload), stdout=sys.stderr, _stderr=sys.stderr,
        )
        return
    emit_board_human(result, payload)

__all__ = [
    "board_payload",
    "coerce_rebuild_outcome",
    "emit_board_human",
    "emit_board_json",
    "emit_board_print",
    "read_board_text",
    "result_board_path",
    "simplify_board_text",
    "source_banner",
    "terminal_needs_plain_board",
    "write_board_rebuild_human",
]
