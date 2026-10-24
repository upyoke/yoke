"""PreToolUse Bash hook: block piping a live long command into a truncator.

The AGENTS.md ``## Command Output — Hard Rule`` names ``<command> | tail -N``
and ``<command> 2>&1 | head`` as anti-patterns on live long-command
invocations, but until this guard no lint owned that clause: the polling
lint only matches temp-path peeks on an existing capture, the subagent
backgrounding lint only denies backgrounding, and the shell-payload lint
classifies bounded ``adapter | tail -N`` on *short* Yoke adapters as
benign. The observed gap shape was a foreground
``watch_pytest -- ... 2>&1 | tail -8``.

Two hazards, both silent: the truncator discards all but the last N lines
of failure context (forcing a re-run to see what broke), and the pipeline
exit code is the truncator's — ``tail`` exits 0, so a failed test run
reads as success to everything keying off ``$?``.

Scope is the named long-command set (watcher wrappers, pytest, the
generic test runner, doctor/deploy engines). Pure read discovery tools
(``rg``, ``grep``, ``ls``, ``find``, ``git grep``) are short commands and
stay exempt — the truncator denial is for the long set, not sub-second
reads. Short Yoke adapters stay out of scope here because
:mod:`yoke_core.domain.lint_yoke_adapter_output_truncation` owns them: it
refuses a truncated ``yoke`` invocation of any duration, and teaches the
narrower read rather than this module's capture-first recipe.

Pattern mirrors :mod:`yoke_core.domain.lint_git_stash_arg_order`: typed
``evaluate(record: HookContext) -> HookDecision`` entry, CLI ``__main__``
form for the legacy stdin invocation, warn/deny applied centrally by the
hook runner's mode gate, suppression token audit-only (never unblocks).
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import shlex
import sys
from typing import List, Optional, Tuple

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_command_extract import (
    extract_command as _extract_command,
    is_unresolved_command_token,
)
from yoke_contracts.hook_runner.shell_statements import iter_pipeline_groups
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-pipe-to-truncator"
SUPPRESSION_TOKEN = "# lint:no-pipe-truncator-check"

# Long-command module ids that count only in ``python -m <module>`` command
# position.  A quoted search pattern or another command's argument may contain
# the same text without invoking the module.
_LONG_MODULE_IDS = (
    "yoke_core.tools.watch_pytest",
    "yoke_core.tools.watch_doctor",
    "yoke_core.tools.watch_merge",
    "yoke_core.tools.run_tests",
    "yoke_core.engines.doctor",
    "yoke_core.engines.deploy",
)

# The taught ``yoke watch <kind>`` spellings, tokenized once so matching is
# anchored to the executable and subcommand rather than raw command text.
_LONG_CLI_TOKEN_PREFIXES = tuple(
    tuple(cli_form(module).split())
    for module in WATCH_CLI_TOKENS
    if module != "yoke_core.tools.watch_tail" and cli_form(module)
)

_TRUNCATORS = frozenset({"tail", "head"})

def _stage_tokens(stage: str) -> List[str]:
    """Tokenize one pipeline stage, dropping leading env assignments/subshell parens."""
    try:
        tokens = shlex.split(stage, posix=True)
    except ValueError:
        tokens = stage.split()
    tokens = [t.lstrip("({") for t in tokens]
    if tokens and tokens[0].rsplit("/", 1)[-1] == "env":
        tokens.pop(0)
        while tokens and tokens[0].startswith("-"):
            tokens.pop(0)
    while tokens and ("=" in tokens[0] and not tokens[0].startswith("-")):
        tokens.pop(0)
    return [t for t in tokens if t]


def _stage_is_long_command(stage: str) -> Optional[str]:
    """Return a short label when *stage* invokes a known long command."""
    tokens = _stage_tokens(stage)
    if not tokens:
        return None
    if "--print-streaming-pair" in tokens:
        return None
    first = tokens[0].rsplit("/", 1)[-1]
    if first == "pytest":
        return "pytest"
    if first.startswith("python"):
        for idx, tok in enumerate(tokens[1:-1], start=1):
            if tok != "-m":
                continue
            module_id = tokens[idx + 1]
            if module_id == "pytest":
                return "pytest"
            if module_id in _LONG_MODULE_IDS:
                return module_id
    for prefix in _LONG_CLI_TOKEN_PREFIXES:
        if tuple(tokens[: len(prefix)]) == prefix:
            return " ".join(prefix)
    return None


def _stage_is_truncator(stage: str) -> bool:
    tokens = _stage_tokens(stage)
    if not tokens:
        return False
    first = tokens[0].rsplit("/", 1)[-1]
    return first in _TRUNCATORS or is_unresolved_command_token(first)


def _find_pipe_to_truncator(command: str) -> Optional[Tuple[str, str]]:
    """Return ``(long_command_label, truncator_stage)`` on a hit, else ``None``.

    Pipeline boundaries come from quote-aware statement/pipe grouping so a
    long-command token inside a quoted pattern or evidence string is not a
    live stage — only unquoted ``|`` joins a long command to a truncator.
    """
    for stages in iter_pipeline_groups(command):
        if len(stages) < 2:
            continue
        for idx, stage in enumerate(stages[:-1]):
            label = _stage_is_long_command(stage)
            if label is None:
                continue
            for later in stages[idx + 1 :]:
                if _stage_is_truncator(later):
                    return (label, later.strip())
    return None


def _format_reason(label: str, truncator: str, suppression_seen: bool) -> str:
    body = (
        "BLOCKED: live long command piped into a truncator "
        f"(`{label}` ... | `{truncator}`).\n\n"
        "Two silent hazards: the truncator discards all but the last lines of\n"
        "failure context (a failed run must be re-run to see what broke), and\n"
        "the pipeline exit code is the TRUNCATOR's — `tail`/`head` exit 0, so\n"
        "a failing run reads as success to anything keying off `$?`.\n\n"
        "Correct shapes:\n"
        "  # watcher wrappers capture internally — run them bare, no pipe:\n"
        "  yoke watch pytest -- <pytest args>\n"
        "  tail -80 <raw-capture>   # separate command, AFTER completion\n"
        "  # other long commands use capture-first:\n"
        "  _tmp=$(mktemp /tmp/yoke-cmd.XXXXXX)\n"
        '  <command> >"$_tmp" 2>&1; _rc=$?\n'
        '  tail -80 "$_tmp" # inspect captured output\n'
        '  grep -E "FAIL|ERROR|error" "$_tmp" || true # extract failures\n'
        '  exit "$_rc"\n'
        "Doctrine: AGENTS.md `## Command Output — Hard Rule`"
    )
    if suppression_seen:
        body = (
            body + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — the "
            "rule still denies. Use the capture-first shape and retry."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Apply the rule; return ``(reason, audit_outcome)`` on a hit."""
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    hit = _find_pipe_to_truncator(command)
    if hit is None:
        return None
    label, truncator = hit
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(label, truncator, suppression_seen)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason, "audit_outcome": outcome},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=_extract_command(payload) or None,
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
