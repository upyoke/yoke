"""Product-safe implementations of client-local hook policies."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from yoke_contracts.hook_runner.main_commit import (
    NO_MAIN_CHECK_SUPPRESSION,
    git_invocations as main_commit_git_invocations,
    is_bookkeeping,
)
from yoke_harness.hooks.decision_render import HOOK_SPECIFIC_OUTPUT_KEY
from yoke_harness.hooks.local_policy_common import (
    ADVISORY,
    DENY,
    NOOP,
    PolicyResult,
    branch,
    command_from_payload,
    cwd_from_payload,
    git,
    git_invocations,
    porcelain,
    repo_cwd,
    response_text,
    staged,
    statements,
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
_GREP_LIKE_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:\S*/)?(?:rg|grep|egrep|fgrep)\b"
)


def lint_main_commit(payload: dict) -> PolicyResult:
    command = command_from_payload(payload)
    for args, repo_path in main_commit_git_invocations(command):
        if not args or args[0] != "commit":
            continue
        if NO_MAIN_CHECK_SUPPRESSION in command:
            continue
        cwd = repo_cwd(payload, repo_path)
        if branch(cwd) not in {"main", "master"}:
            continue
        files = [path for path in staged(cwd) if not is_bookkeeping(path)]
        if not files:
            continue
        listed = "\n  ".join(files[:10])
        return PolicyResult(
            DENY,
            "BLOCKED: Implementation commit on main branch.\n\n"
            f"Staged implementation files:\n  {listed}\n\n"
            "Worktree discipline: implementation code must be committed "
            "in a worktree branch, not directly on main.",
        )
    return PolicyResult(NOOP)


def _destructive_shape(args: list[str]) -> str:
    if not args:
        return ""
    verb, rest = args[0], args[1:]
    if verb == "reset" and "--hard" in rest:
        return "git reset --hard"
    if verb == "checkout" and "--" in rest:
        return "git checkout -- <path>"
    if verb == "checkout" and any(arg in {"-f", "--force"} for arg in rest):
        return "git checkout -f <branch>"
    if verb == "restore" and (
        "--worktree" in rest or any(not a.startswith("-") for a in rest)
    ):
        return "git restore --worktree <path>"
    if verb == "clean" and any(
        arg == "--force" or (arg.startswith("-") and "f" in arg) for arg in rest
    ):
        return "git clean -f"
    if verb == "stash" and rest and rest[0] in {"drop", "clear"}:
        return f"git stash {rest[0]}"
    return ""


def lint_destructive_git(payload: dict) -> PolicyResult:
    command = command_from_payload(payload)
    for args, repo_path in git_invocations(command):
        shape = _destructive_shape(args)
        if not shape:
            continue
        cwd = repo_cwd(payload, repo_path)
        modified, untracked = porcelain(cwd)
        threatened = modified if shape != "git clean -f" else untracked
        if shape.startswith("git stash"):
            stash = git(cwd, "stash", "list")
            threatened = stash.stdout.splitlines() if stash and stash.returncode == 0 else []
        if not threatened:
            continue
        listed = "\n  ".join(threatened[:10])
        return PolicyResult(
            DENY,
            "BLOCKED: destructive git command would wipe uncommitted changes.\n\n"
            f"Shape: {shape}\nFiles at risk:\n  {listed}\n\n"
            "Remediation: stash or commit work before retrying.",
        )
    return PolicyResult(NOOP)


def _double_quoted_spans(text: str) -> list[str]:
    spans: list[str] = []
    current: list[str] = []
    in_double = False
    escaped = False
    for char in text:
        if escaped:
            if in_double:
                current.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            if in_double:
                spans.append("".join(current))
                current = []
                in_double = False
            else:
                in_double = True
            continue
        if in_double:
            current.append(char)
    return spans


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


def _segment_until_shell_separator(text: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not in_single:
            escaped = True
            index += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if text.startswith("&&", index) or text.startswith("||", index):
                return text[:index]
            if char in ";|":
                return text[:index]
        index += 1
    return text


def lint_shell_backtick_search(payload: dict) -> PolicyResult:
    command = command_from_payload(payload)
    for match in _GREP_LIKE_RE.finditer(command):
        segment = _segment_until_shell_separator(command[match.end():])
        for span in _double_quoted_spans(segment):
            if _has_unescaped_backtick(span):
                return PolicyResult(
                    DENY,
                    "BLOCKED: grep/rg search text contains a backtick inside "
                    "double quotes. Backticks still run command substitution "
                    "there; use single quotes for literal Markdown/code searches.",
                )
    return PolicyResult(NOOP)


def lint_workspace_cwd_match(payload: dict) -> PolicyResult:
    workspace = os.environ.get("YOKE_BOUND_WORKSPACE", "").strip()
    if not workspace:
        return PolicyResult(NOOP)
    cwd = cwd_from_payload(payload)
    try:
        Path(cwd).resolve().relative_to(Path(workspace).resolve())
        return PolicyResult(NOOP)
    except (OSError, ValueError):
        pass
    command = command_from_payload(payload)
    writer = any(
        tokens[:1] == ["pytest"]
        or tokens[:3] in (
            ["python", "-m", "pytest"],
            ["python3", "-m", "pytest"],
            ["python", "-m", "yoke_core.domain.agents_render"],
            ["python3", "-m", "yoke_core.domain.agents_render"],
            ["python", "-m", "yoke_core.tools.run_tests"],
            ["python3", "-m", "yoke_core.tools.run_tests"],
        )
        for tokens in statements(command)
    )
    if not writer:
        return PolicyResult(NOOP)
    return PolicyResult(
        DENY,
        "BLOCKED: writer-class command invoked from a cross-checkout cwd.\n\n"
        f"Bound workspace: {workspace}\nCurrent cwd:     {cwd}",
    )


def lint_tmp_runtime_import(payload: dict) -> PolicyResult:
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


def hint_file_line(payload: dict) -> PolicyResult:
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


def db_error_advisory(payload: dict) -> PolicyResult:
    command = command_from_payload(payload)
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
    if schema_hint and any(token in command for token in ("sqlite3", "db_router query")):
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


def deny_stdout(reason: str, event_name: str, executor: str) -> tuple[str, int]:
    body = {
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": "PreToolUse" if event_name == "apply_patch" else event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return json.dumps(body), 0 if executor.startswith("codex") else 2


def advisory_stdout(contexts: list[str], event_name: str) -> str:
    return json.dumps({
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": event_name,
            "additionalContext": "\n\n".join(contexts),
        }
    })


__all__ = [
    "PolicyResult",
    "advisory_stdout",
    "db_error_advisory",
    "deny_stdout",
    "hint_file_line",
    "lint_destructive_git",
    "lint_main_commit",
    "lint_shell_backtick_search",
    "lint_tmp_runtime_import",
    "lint_workspace_cwd_match",
]
