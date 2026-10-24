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

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import re
import sys
from typing import Optional

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


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


def _extract_tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def evaluate_bash_command(command: str | ShellParse) -> Optional[str]:
    """Return a denial reason for a Bash command, or None.

    Heredoc bodies are input: the command-text rules read the parse's
    ``code``, and a body is checked only when its opener line writes a
    test file.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    text = parsed.command
    if not text or "# lint:no-tc-label-check" in text:
        return None
    code = parsed.code
    if NUMERIC_HC_ANY_RE.search(code):
        if NUMERIC_HC_WRITE_RE.search(code) or NUMERIC_HC_COPY_RE.search(code):
            return DENY_NUMERIC_HC
    if writes_test_file(code) and is_sequential_tc(code):
        return DENY_TC_BASH
    for heredoc in parsed.heredocs:
        line_start = text.rfind("\n", 0, heredoc.source_operator_start) + 1
        line_end = text.find("\n", heredoc.source_operator_end)
        opener_line = text[line_start : line_end if line_end >= 0 else len(text)]
        if writes_test_file(opener_line) and is_sequential_tc(heredoc.body):
            return DENY_TC_HEREDOC
    return None


def evaluate_payload(payload: dict, tool_name: Optional[str]) -> Optional[str]:
    """Apply the rules for ``tool_name``, returning a denial reason or None."""
    tool_input = _extract_tool_input(payload)

    if tool_name == "Bash":
        return evaluate_bash_command(extract_command(payload))

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


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry: evaluate Bash/Write payload for TC-label or numeric-HC violations."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    if record.tool_name == "Bash":
        reason = evaluate_bash_command(record.shell)
    else:
        reason = evaluate_payload(payload, record.tool_name)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = attach_check_id(reason, check_id="lint-tc-label")
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=extract_command(payload) or None,
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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
