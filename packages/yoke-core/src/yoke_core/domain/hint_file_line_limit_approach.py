"""PreToolUse Write hint: warn before a Write pushes a file over the 350-line cap.

The commit-time gate (``file_line_check``) catches over-cap writes but
only at ``git commit`` — by then the agent has invested several tool
calls drafting content that won't ship. This hint fires earlier: on
``PreToolUse(Write)``, it counts the would-be lines and emits a
passive ``additionalContext`` reminder when the new file would land
over the 350-line cap (matching the same three rules
``file_line_check`` applies: new over-cap file, growth past cap, or
further growth of an already-over-cap file).

The hint is advisory — it does NOT deny. The commit gate is the
structural backstop. Goal here is to save the agent from drafting
50 extra lines that the commit will refuse.

Failure posture is fail-open: any payload-shape error, classification
miss, or filesystem read failure exits with NOOP so a hint defect
cannot block tool use.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Optional

from yoke_core.domain.file_line_check import (
    LIMIT,
    Classification,
    classify_path,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


TARGET_TOOL = "Write"


def _resolve_repo_root() -> pathlib.Path:
    explicit = os.environ.get("YOKE_TARGET_REPO_ROOT")
    if explicit:
        return pathlib.Path(explicit)
    return pathlib.Path(os.environ.get("YOKE_REPO_ROOT") or os.getcwd())


def _extract_write_fields(payload: dict) -> tuple[str, str]:
    """Return ``(file_path, content)`` from a Write payload, or ``("", "")``."""
    tool_input = (
        payload.get("tool_input")
        or payload.get("toolInput")
        or payload.get("input")
        or {}
    )
    if not isinstance(tool_input, dict):
        return "", ""
    fp = tool_input.get("file_path") or tool_input.get("filePath") or ""
    content = tool_input.get("content") or tool_input.get("body") or ""
    return (fp if isinstance(fp, str) else "",
        content if isinstance(content, str) else "")


def _count_lines(text: str) -> int:
    """Count lines in ``text`` matching git's view of a file with trailing newline."""
    if not text:
        return 0
    if text.endswith("\n"):
        return text.count("\n")
    return text.count("\n") + 1


def _read_existing_count(abs_path: pathlib.Path) -> int:
    if not abs_path.is_file():
        return 0
    try:
        return _count_lines(abs_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return 0


def _build_hint(file_path: str, old: int, new: int) -> str:
    """Build the additionalContext reminder string."""
    delta = "new file" if old == 0 else f"{old} -> {new}"
    return (
        "<system-reminder>\n"
        f"This Write would land `{file_path}` at {new} lines, over the "
        f"{LIMIT}-line authored-file cap ({delta}).\n"
        "\n"
        "The commit-time gate (`file_line_check`) will refuse the "
        "commit. Cheap options to bring the file under cap, in "
        "preference order:\n"
        "  1. Compress in-file: collapse multi-line returns, drop "
        "redundant docstrings, inline one-line `__all__` lists, fold "
        "duplicate teaching. Most files have 5-15 lines of slack.\n"
        "  2. Split a self-contained chunk into a sibling module "
        "(`<name>_<topic>.py`) and re-export from the original.\n"
        "  3. Drop dated / superseded content.\n"
        "\n"
        "Do NOT add normal source files as `file_line_exception` entries "
        "in `.yoke/project.config`. Those are for intentionally "
        "unsplittable artifacts or "
        "non-authored data. Hard-rule files like AGENTS.md / CLAUDE.md "
        "must stay under the cap; the cap forces the discipline to merge / "
        "compress / retire teaching that no longer pays for itself.\n"
        "</system-reminder>"
    )


def evaluate_fields(
    file_path: str,
    content: str,
    existing_line_count: int,
    classification: Classification,
    limit: int = LIMIT,
) -> Optional[str]:
    """Return the hint string when the Write would put the file over cap.

    Rules mirror ``file_line_check.changed_files_check``:
      1. new (file didn't exist) AND new_count > limit → hint.
      2. existing under cap AND new_count > limit → hint.
      3. existing over cap AND new_count > existing → hint.
    """
    if not file_path:
        return None
    if classification != Classification.AUTHORED:
        return None
    new = _count_lines(content)
    if new <= limit and existing_line_count <= limit:
        return None
    if existing_line_count > limit and new <= existing_line_count:
        return None
    if new <= limit:
        return None
    return _build_hint(file_path, existing_line_count, new)


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. NOOP + additionalContext when Write would over-cap a file."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    if record.tool_name != TARGET_TOOL and payload.get("tool_name") != TARGET_TOOL:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    file_path, content = _extract_write_fields(payload)
    if not file_path:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    repo_root = _resolve_repo_root()
    try:
        abs_path = pathlib.Path(file_path)
        if not abs_path.is_absolute():
            abs_path = repo_root / file_path
        rel = abs_path.relative_to(repo_root).as_posix() if abs_path.is_absolute() \
            and str(abs_path).startswith(str(repo_root)) else file_path
        classification = classify_path(rel, repo_root=repo_root)
        existing = _read_existing_count(abs_path)
    except (ValueError, OSError):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    hint = evaluate_fields(file_path, content, existing, classification)
    if hint is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": hint},
        next=Next.CONTINUE,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    tool = payload.get("tool_name")
    sid = payload.get("session_id")
    cwd = payload.get("cwd")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool if isinstance(tool, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> emit hookSpecificOutput envelope."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    ctx = decision.audit_fields.get("additionalContext") if decision.audit_fields else None
    if ctx:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "additionalContext": ctx
        }}))
    return 0


__all__ = ["TARGET_TOOL", "evaluate", "evaluate_fields", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
