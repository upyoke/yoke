"""Product-safe implementations of client-local hook policies."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from yoke_contracts.hook_runner import (
    destructive_git_messages,
    destructive_git_rules,
    recursive_rm_guard,
)
from yoke_contracts.hook_runner.local_privacy_guard import classify_shell_command
from yoke_contracts.hook_runner.main_commit import git_invocations
from yoke_contracts.hook_runner.shell_expansion_scan import double_quoted_spans
from yoke_contracts.hook_runner.shell_parse import ShellParse
from yoke_contracts.hook_runner.local_privacy_messages import (
    LIVE_ADVISORY,
    LIVE_DENY,
)
from yoke_harness.hooks.decision_render import HOOK_SPECIFIC_OUTPUT_KEY
from yoke_harness.hooks.local_policy_common import (
    ADVISORY,
    DENY,
    NOOP,
    PolicyResult,
    cwd_from_payload,
    git,
    repo_cwd,
    response_text,
    write_fields,
)


_TMP_PREFIXES = ("/tmp/", "/var/folders/", "/private/tmp/", "/private/var/folders/")
_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(?:yoke_core|yoke_cli|yoke_harness|runtime(?:\.(?:api|harness))?)\b",
    re.MULTILINE,
)
_SCHEMA_HINT_RE = re.compile(
    r"^(?:Error|sqlite3\.OperationalError):\s*no such (column|table)(?::\s*([\w.]+))?",
    re.IGNORECASE | re.MULTILINE,
)
_SEARCH_PROGRAMS = frozenset({"rg", "grep", "egrep", "fgrep"})


def lint_destructive_git(payload: dict, shell: ShellParse) -> PolicyResult:
    """Apply the shared destructive-git and recursive-rm rules.

    ``worktree remove`` and the claimed-worktree ``rm`` check are engine-only.
    """
    suppression_seen = destructive_git_messages.SUPPRESSION_TOKEN in shell.command
    refusal = recursive_rm_guard.recursive_rm_refusal(shell, cwd_from_payload(payload))
    if refusal is not None:
        return PolicyResult(
            DENY,
            destructive_git_messages.format_recursive_rm_reason(
                refusal.shape, list(refusal.targets), suppression_seen
            ),
        )
    for args, repo_path in git_invocations(shell):
        cwd = repo_cwd(payload, repo_path)
        shape = destructive_git_rules.classify_shape(args, cwd)
        if shape is None or shape == "worktree_remove":
            continue
        threatened = destructive_git_rules.threatened_state(shape, cwd, args, git)
        if not threatened:
            continue
        return PolicyResult(
            DENY,
            destructive_git_messages.format_reason(
                shape, threatened, suppression_seen
            ),
        )
    return PolicyResult(NOOP)


def _has_unescaped_backtick(span: str) -> bool:
    escaped = False
    for char in span:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "`":
            return True
    return False


def lint_shell_backtick_search(payload: dict, shell: ShellParse) -> PolicyResult:
    for segment in shell.segments:
        if segment.program not in _SEARCH_PROGRAMS:
            continue
        if any(_has_unescaped_backtick(span) for span in double_quoted_spans(segment.text)):
            return PolicyResult(
                DENY,
                "BLOCKED: grep/rg search text contains a backtick inside "
                "double quotes. Backticks still run command substitution "
                "there; use single quotes for literal Markdown/code searches.",
            )
    return PolicyResult(NOOP)


def lint_local_privacy(payload: dict, shell: ShellParse) -> PolicyResult:
    """Mirror the engine guard: deny the privacy database, advise broad scans.

    Personal-folder reads and GUI automation are the harness prompt's and the
    operating system's call, so they classify but produce nothing here.
    """
    finding = classify_shell_command(
        shell,
        home=Path.home(),
        cwd=payload.get("cwd") if isinstance(payload.get("cwd"), str) else Path.cwd(),
    )
    if finding is None:
        return PolicyResult(NOOP)
    severity = finding.live_severity
    if severity == LIVE_DENY:
        return PolicyResult(DENY, finding.reason())
    if severity == LIVE_ADVISORY:
        return PolicyResult(ADVISORY, additional_context=finding.reason())
    return PolicyResult(NOOP)


def lint_tmp_runtime_import(payload: dict, shell: ShellParse) -> PolicyResult:
    file_path, content = write_fields(payload)
    if not file_path.endswith(".py") or not file_path.startswith(_TMP_PREFIXES):
        return PolicyResult(NOOP)
    if not _IMPORT_RE.search(content):
        return PolicyResult(NOOP)
    return PolicyResult(
        DENY,
        "BLOCKED: Python script under /tmp imports Yoke implementation modules "
        "and will not resolve packages from its script directory.",
    )


def hint_file_line(payload: dict, shell: ShellParse) -> PolicyResult:
    file_path, content = write_fields(payload)
    if not file_path:
        return PolicyResult(NOOP)
    lines = content.count("\n") if content.endswith("\n") else content.count("\n") + 1
    if lines <= 350:
        return PolicyResult(NOOP)
    return PolicyResult(
        ADVISORY,
        additional_context=(
            f"This Write would land `{file_path}` at {lines} lines, over the "
            "350-line authored-file cap. Split or compress before committing."
        ),
    )


def db_error_advisory(payload: dict, shell: ShellParse) -> PolicyResult:
    command = shell.command
    output = response_text(payload)
    messages: list[str] = []
    repo_root = os.environ.get("YOKE_REPO_ROOT", "").strip()
    if repo_root:
        stray = Path(repo_root) / "yoke.db"
        if stray.is_file():
            if stray.stat().st_size == 0:
                try:
                    stray.unlink()
                except OSError:
                    pass
            messages.append(
                f"HARD STOP: This Bash command created a stray repo-root yoke.db at {stray}."
            )
    schema_hint = _SCHEMA_HINT_RE.search(output)
    if schema_hint and any(
        token in command for token in ("sqlite3", "db_router query")
    ):
        kind = schema_hint.group(1).lower()
        name = schema_hint.group(2) or "(unnamed)"
        messages.append(
            f"HARD STOP: query references unknown {kind} `{name}`. "
            "Do NOT keep guessing; verify the schema surface."
        )
    elif re.search(r"^sqlite3\.[A-Za-z]+Error:", output, re.MULTILINE):
        messages.append("HARD STOP: DB query FAILED in a Python traceback.")
    if not messages:
        return PolicyResult(NOOP)
    return PolicyResult(ADVISORY, additional_context="\n".join(messages))


def advisory_stdout(contexts: list[str], event_name: str) -> str:
    return json.dumps(
        {
            HOOK_SPECIFIC_OUTPUT_KEY: {
                "hookEventName": event_name,
                "additionalContext": "\n\n".join(contexts),
            }
        }
    )


__all__ = [
    "PolicyResult",
    "advisory_stdout",
    "db_error_advisory",
    "hint_file_line",
    "lint_destructive_git",
    "lint_local_privacy",
    "lint_shell_backtick_search",
    "lint_tmp_runtime_import",
]
