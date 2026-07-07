"""PreToolUse hook: block sequential TC-N labels and numeric HC test filenames.

Python owner for ``.agents/skills/yoke/scripts/lint-tc-label.sh``.

Handles both Bash and Write tool calls:

* Bash — scans commands that create/modify test files under
  ``.agents/skills/yoke/scripts/tests/`` (or the ``.claude/`` compatibility
  path) for sequential ``TC-<number>`` labels, including labels inside
  heredoc bodies, and for numeric ``test-doctor-hc<number>.sh`` filenames
  being created.
* Write — scans ``file_path`` for numeric HC filenames, and scans the
  ``content`` for sequential TC labels when writing to a test file.

Suppression: ``# lint:no-tc-label-check`` either in the Bash command or
inside the content being written.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is
preserved for the registered shell hook; exit code is always ``0``.
"""

from __future__ import annotations

import functools
import json
import os
import re
import sys
from typing import Iterator, Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


TC_LABEL_RE = re.compile(r"\bTC-\d+\b")
TEST_FILE_PATH_RE = re.compile(r"\.(?:agents|claude)/skills/yoke/scripts/tests/")
TEST_FILE_WRITE_RE = re.compile(
    r"(?:>|>>)\s*\S*\.(?:agents|claude)/skills/yoke/scripts/tests/\S+"
)
TEST_FILE_WRITE_CMD_RE = re.compile(
    r"\b(?:cp|mv|touch|tee)\b[^\n]*\.(?:agents|claude)/skills/yoke/scripts/tests/\S+"
)
NUMERIC_HC_RE = re.compile(r"^test-doctor-hc\d+\.sh$")
NUMERIC_HC_ANY_RE = re.compile(r"test-doctor-hc\d+\.sh")
NUMERIC_HC_WRITE_RE = re.compile(
    r"(?:>|>>|cp\s|mv\s|touch\s|cat\s*>|tee\s)\s*\S*test-doctor-hc\d+\.sh"
)
NUMERIC_HC_COPY_RE = re.compile(r"(?:cp|mv)\s+\S+\s+\S*test-doctor-hc\d+\.sh")

_SQ = chr(39)
HEREDOC_START_RE = re.compile(
    r"(?P<prefix><<(?P<dash>-?)[ \t]*)[" + _SQ + r"\"" + r"]?(?P<delim>\w+)[" + _SQ + r"\"" + r"]?(?P<suffix>[^\n]*\n)"
)


DENY_NUMERIC_HC = (
    "BLOCKED: Numeric HC test filename detected.\n\n"
    "Test files for doctor health checks must use descriptive names,\n"
    "not numeric suffixes like test-doctor-hc<number>.sh.\n\n"
    "Use: test-doctor-hc-schema-drift.sh (descriptive)\n"
    "Not:  test-doctor-hc<number>.sh (numeric)\n\n"
    "Suppress with: # lint:no-tc-label-check"
)

DENY_NUMERIC_HC_WRITE = (
    "BLOCKED: Numeric HC test filename detected.\n\n"
    "Test files for doctor health checks must use descriptive names,\n"
    "not numeric suffixes like test-doctor-hc<number>.sh.\n\n"
    "Use: test-doctor-hc-schema-drift.sh (descriptive)\n"
    "Not:  test-doctor-hc<number>.sh (numeric)\n\n"
    "Suppress with: add # lint:no-tc-label-check to the file content"
)

DENY_TC_BASH = (
    "BLOCKED: Sequential TC-<number> label detected in test file context.\n\n"
    "Test cases must use descriptive labels, not sequential numbers.\n\n"
    "Use: TC-blocks-direct-sqlite (descriptive)\n"
    "Not:  TC-<number> (sequential numeric)\n\n"
    "Suppress with: # lint:no-tc-label-check"
)

DENY_TC_HEREDOC = (
    "BLOCKED: Sequential TC-<number> label detected in heredoc test-file write.\n\n"
    "Test cases must use descriptive labels, not sequential numbers.\n\n"
    "Use: TC-blocks-direct-sqlite (descriptive)\n"
    "Not:  TC-<number> (sequential numeric)\n\n"
    "Suppress with: # lint:no-tc-label-check"
)

DENY_TC_WRITE = (
    "BLOCKED: Sequential TC-<number> label detected in test file.\n\n"
    "Test cases must use descriptive labels, not sequential numbers.\n\n"
    "Use: TC-blocks-direct-sqlite (descriptive)\n"
    "Not:  TC-<number> (sequential numeric)\n\n"
    "Suppress with: add # lint:no-tc-label-check to the file content"
)


def is_sequential_tc(text: str) -> bool:
    """Return True when *text* contains any purely-numeric ``TC-N`` label.

    Named labels like ``TC-42-slow-path`` are ignored.
    """
    for match in TC_LABEL_RE.finditer(text):
        end = match.end()
        if end < len(text) and (text[end].isalpha() or text[end] in "_-"):
            continue
        return True
    return False


def has_numeric_hc_filename(path: str) -> bool:
    """Return True when *path* is a bare numeric HC test file basename."""
    basename = os.path.basename(path)
    return bool(NUMERIC_HC_RE.match(basename))


def writes_test_file(text: str) -> bool:
    """Return True when *text* looks like it writes to a test file."""
    return bool(TEST_FILE_WRITE_RE.search(text) or TEST_FILE_WRITE_CMD_RE.search(text))


@functools.lru_cache(maxsize=64)
def _heredoc_close_pattern(dash: str, delim: str) -> "re.Pattern[str]":
    """Return (and cache) the closing-line regex for a heredoc delimiter."""
    return re.compile(
        r"(?m)^"
        + (r"\t*" if dash == "-" else "")
        + re.escape(delim)
        + r"\b"
    )


def iter_heredocs(text: str) -> Iterator[Tuple[str, str]]:
    """Yield ``(opener_line, body)`` tuples for each heredoc in *text*."""
    pos = 0
    while True:
        opener = HEREDOC_START_RE.search(text, pos)
        if opener is None:
            return
        close_pat = _heredoc_close_pattern(opener.group("dash"), opener.group("delim"))
        closer = close_pat.search(text, opener.end())
        if closer is None:
            return
        line_start = text.rfind("\n", 0, opener.start()) + 1
        line_end = text.find("\n", opener.end())
        if line_end == -1:
            line_end = len(text)
        yield text[line_start:line_end], text[opener.end():closer.start()]
        pos = closer.end()


def strip_heredoc_bodies(text: str) -> str:
    """Replace heredoc bodies with a placeholder so they don't mask matches."""
    parts: list[str] = []
    pos = 0
    while True:
        opener = HEREDOC_START_RE.search(text, pos)
        if opener is None:
            parts.append(text[pos:])
            return "".join(parts)
        close_pat = _heredoc_close_pattern(opener.group("dash"), opener.group("delim"))
        closer = close_pat.search(text, opener.end())
        if closer is None:
            parts.append(text[pos:])
            return "".join(parts)
        parts.append(text[pos:opener.start()])
        parts.append(
            opener.group("prefix")
            + "HEREDOC_STRIPPED"
            + opener.group("suffix")
        )
        pos = closer.end()


def _extract_tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def evaluate_payload(payload: dict) -> Optional[str]:
    """Apply the rules, returning a denial reason or None."""
    tool_name = _tool_name(payload)
    tool_input = _extract_tool_input(payload)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not isinstance(command, str) or command == "":
            return None
        if "# lint:no-tc-label-check" in command:
            return None

        stripped = strip_heredoc_bodies(command)

        if NUMERIC_HC_ANY_RE.search(stripped):
            if NUMERIC_HC_WRITE_RE.search(stripped) or NUMERIC_HC_COPY_RE.search(stripped):
                return DENY_NUMERIC_HC

        if writes_test_file(stripped) and is_sequential_tc(stripped):
            return DENY_TC_BASH

        for heredoc_line, heredoc_body in iter_heredocs(command):
            if writes_test_file(heredoc_line) and is_sequential_tc(heredoc_body):
                return DENY_TC_HEREDOC
        return None

    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        if not isinstance(file_path, str):
            file_path = ""
        if not isinstance(content, str):
            content = ""
        if "# lint:no-tc-label-check" in content:
            return None
        if has_numeric_hc_filename(file_path):
            return DENY_NUMERIC_HC_WRITE
        if TEST_FILE_PATH_RE.search(file_path) and is_sequential_tc(content):
            return DENY_TC_WRITE
        return None

    return None


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _emit_denial(payload: dict, reason: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    tool = _tool_name(payload)
    tool_input = _extract_tool_input(payload)
    # Bash deniers surface the command; Write deniers surface the file_path.
    command_snippet = ""
    if tool == "Bash":
        cmd = tool_input.get("command") or tool_input.get("cmd")
        if isinstance(cmd, str):
            command_snippet = cmd
    else:
        fp = tool_input.get("file_path")
        if isinstance(fp, str):
            command_snippet = fp
    try:
        emit_denial_event(
            hook="lint-tc-label",
            tool=tool if isinstance(tool, str) else "",
            check_id="lint-tc-label",
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            command_snippet=command_snippet,
        )
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry: evaluate Bash/Write payload for TC-label or numeric-HC violations."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    reason = evaluate_payload(payload)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = append_field_note_footer(reason, rule_id="lint-tc-label")
    _emit_denial(payload, reason)
    envelope = json.dumps(_build_deny_response(reason))
    return HookDecision(
        outcome=Outcome.DENY,
        message=envelope,
        audit_fields={"reason": reason},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_input = _extract_tool_input(payload)
    raw_cmd = tool_input.get("command")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_tool_name(payload) or None,
        command_body=raw_cmd if isinstance(raw_cmd, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
