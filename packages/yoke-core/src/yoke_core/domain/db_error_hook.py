"""Python owner for the DB-error PostToolUse hook.

Front door for the analyzer pipeline: orchestrates stray-DB detection,
DB query failure detection, and row-count collapse detection, and exposes
the ``run``/``main`` CLI entry consumed by the deployed harness hook
configuration. Each analysis seam lives in a focused sibling module:

- ``db_error_hook_stray`` — StrayDbResult + detect_stray_db
- ``db_error_hook_query_failure`` — detect_db_query_failure
- ``db_error_hook_collapse`` — DDL_PATTERNS, CRITICAL_TABLES,
  CollapseEntry, CollapseResult, check_row_count_collapse,
  _emit_data_loss_event

Note: Module named ``db_error_hook`` (not ``sqlite3_error_hook``) to avoid
triggering filename-based lints during git operations.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.db_error_hook_collapse import (
    CRITICAL_TABLES,
    DDL_PATTERNS,
    CollapseEntry,
    CollapseResult,
    check_row_count_collapse,
)
from yoke_core.domain.db_error_hook_query_failure import detect_db_query_failure
from yoke_core.domain.db_error_hook_stray import StrayDbResult, detect_stray_db
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


__all__ = [
    "CRITICAL_TABLES",
    "DDL_PATTERNS",
    "CollapseEntry",
    "CollapseResult",
    "StrayDbResult",
    "analyze_bash_output",
    "check_row_count_collapse",
    "detect_db_query_failure",
    "detect_stray_db",
    "evaluate",
    "main",
    "run",
]


def analyze_bash_output(
    command: str,
    response_content: str,
    repo_root: str = "",
    db_path: str = "",
    script_dir: str = "",
    session_id: str = "",
) -> Optional[str]:
    """Run all DB-error-hook checks and return combined message or None."""
    messages: list[str] = []

    if repo_root:
        stray = detect_stray_db(repo_root, command)
        if stray.message:
            messages.append(stray.message)

    db_query_msg = detect_db_query_failure(command, response_content)
    if db_query_msg:
        messages.append(db_query_msg)

    if db_path:
        collapse = check_row_count_collapse(db_path, command, session_id, script_dir)
        if collapse.message:
            messages.append(collapse.message)

    return "\n".join(messages) if messages else None


def _tool_command(data: dict[str, Any]) -> str:
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command", "")
    return command if isinstance(command, str) else ""


def _response_content(data: dict[str, Any]) -> str:
    response = data.get("tool_response", {})
    if isinstance(response, dict):
        content = response.get("content", "")
        if isinstance(content, list):
            return " ".join(
                str(c.get("text", "")) if isinstance(c, dict) else str(c)
                for c in content
            )
        return content if isinstance(content, str) else str(content)
    if isinstance(response, str):
        return response
    return str(response)


def _advisory_for_payload(
    data: dict[str, Any],
    *,
    repo_root: str,
    db_path: str,
    script_dir: str,
    session_id: str,
) -> Optional[str]:
    return analyze_bash_output(
        command=_tool_command(data),
        response_content=_response_content(data),
        repo_root=repo_root,
        db_path=db_path,
        script_dir=script_dir,
        session_id=session_id,
    )


def run(stdin_data: str) -> None:
    """Run the DB-error-hook pipeline against a PostToolUse payload string.

    extracted from ``main`` so other Python hook runners (notably
    ``codex_hooks.run_post_tool_use``) can call the analyzer directly
    without a shell or stdin round-trip.
    """
    if not stdin_data:
        return

    try:
        data = json.loads(stdin_data)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return

    result = _advisory_for_payload(
        data,
        repo_root=os.environ.get("YOKE_REPO_ROOT", ""),
        db_path=os.environ.get("YOKE_DB_PATH", ""),
        script_dir=os.environ.get("YOKE_SCRIPT_DIR", ""),
        session_id=resolve_ambient_session_id() or "",
    )

    if result:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": result,
            }
        }
        print(json.dumps(output))


def evaluate(record: HookContext) -> HookDecision:
    """Typed PostToolUse DB-error advisory. Fail-open; never blocks the chain."""
    try:
        payload = record.payload if isinstance(record.payload, dict) else {}
        if not payload:
            return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
        repo_root = (
            record.target_root
            or record.cwd
            or os.environ.get("YOKE_REPO_ROOT", "")
            or ""
        )
        result = _advisory_for_payload(
            payload,
            repo_root=repo_root,
            db_path=os.environ.get("YOKE_DB_PATH", ""),
            script_dir=os.environ.get("YOKE_SCRIPT_DIR", ""),
            session_id=record.session_id or resolve_ambient_session_id() or "",
        )
        if result:
            return HookDecision(
                outcome=Outcome.NOOP,
                audit_fields={"additionalContext": result},
                next=Next.CONTINUE,
            )
    except Exception:
        pass
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def main() -> None:
    """CLI: reads PostToolUse JSON from stdin, prints hook output."""
    import sys

    stdin_data = sys.stdin.read()
    if not stdin_data:
        sys.exit(0)
    run(stdin_data)


if __name__ == "__main__":
    main()
