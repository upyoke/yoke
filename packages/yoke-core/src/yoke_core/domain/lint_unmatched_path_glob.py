"""PreToolUse Bash hook: refuse unmatched path globs only under zsh.

zsh NOMATCH aborts the command before the tool runs when an unquoted path
glob such as ``docs/deploy*`` expands to nothing. Quoted patterns, heredoc
bodies (quoted or not — zsh never glob-expands them), and globs that do
expand stay out of scope. The denial names ``rg --files`` as the
enumeration alternative.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.shell_guard_repairs import (
    RIPGREP_REPLACE_CHECK_ID,
    executing_shell,
    expanded_glob_path,
    find_unmatched_path_glob,
    glob_repair,
    ripgrep_replace_repair,
)
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_session_cwd_target_extract import resolve_payload_cwd
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import (
    extract_command as _extract_command,
    raw_command as _raw_command,
)

CHECK_ID = "lint-unmatched-path-glob"
SUPPRESSION_TOKEN = "# lint:no-unmatched-glob-check"


def _extract_cwd(payload: dict, fallback: str = "") -> str:
    return resolve_payload_cwd(payload, fallback=fallback)


def _payload_cwd(payload: dict) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) else ""


def _format_reason(
    token: str,
    suppression_seen: bool,
    *,
    execution_cwd: str = "",
    payload_cwd: str = "",
    command: ShellParse | None = None,
) -> str:
    body = (
        "BLOCKED: unquoted path glob matches no files after home and cwd resolution.\n\n"
        f"Detected: `{token}`\n"
        f"Checked pattern: `{expanded_glob_path(token, execution_cwd)}`\n"
    )
    if execution_cwd:
        body += f"Checked tree: `{execution_cwd}`\n"
    if payload_cwd and payload_cwd != execution_cwd:
        body += f"Payload cwd was `{payload_cwd}`.\n"
    body += (
        "\n"
        "zsh NOMATCH aborts the command before the tool runs. Enumerate "
        "candidates with `rg --files`, or quote a pattern the tool consumes:\n"
        "  rg --files | rg 'name-or-symbol'\n"
        "  rg --glob 'docs/deploy*' PATTERN\n\n"
        "Do not pass an optional unmatched path glob such as `docs/deploy*` "
        "directly to zsh."
    )
    if command is not None:
        repair = glob_repair(command, token, execution_cwd)
        if repair is not None:
            repaired, matches = repair
            body += "\n\nRepaired command: `" + repaired + "`"
            body += "\nFiles matching the stem: " + (
                ", ".join(matches) if matches else "none"
            )
            body += "\nIf `rg` is absent, enumerate tracked files with `git ls-files`."
    if suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(
    payload: dict,
    *,
    fallback_cwd: str = "",
    shell: ShellParse | None = None,
) -> Optional[Tuple[str, str]]:
    """Return ``(reason, audit_outcome)`` on a hit, else None.

    ``shell`` is the hook call's shared parse of the extracted command.
    """
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    reuse = shell is not None and shell.command == command
    parsed = shell if reuse else parse_shell(command)
    repair = ripgrep_replace_repair(parsed)
    if repair is not None:
        reason = attach_check_id(
            "BLOCKED: `rg -r` means `--replace`, not recursive search. "
            f"Repaired command: `{repair}`",
            check_id=RIPGREP_REPLACE_CHECK_ID,
        )
        return reason, "denied"
    if executing_shell(payload) != "zsh":
        return None
    execution_cwd = _extract_cwd(payload, fallback=fallback_cwd)
    # Assignment substitution removes ``$`` before the glob walk. Keep the
    # raw text so an unexpanded variable is allowed instead of denied as a
    # literal path.
    source = _raw_command(payload) or command
    walked = parsed if source == command else parse_shell(source)
    found = find_unmatched_path_glob(walked, execution_cwd)
    if found is None:
        return None
    token, checked_cwd = found
    suppression_seen = SUPPRESSION_TOKEN in source
    reason = _format_reason(
        token,
        suppression_seen,
        execution_cwd=checked_cwd,
        payload_cwd=_payload_cwd(payload),
        command=walked,
    )
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload, fallback_cwd=record.cwd or "", shell=record.shell)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    audit = {
        "reason": reason,
        "audit_outcome": outcome,
        "check_id": RIPGREP_REPLACE_CHECK_ID
        if f"Yoke check id: {RIPGREP_REPLACE_CHECK_ID}" in reason
        else CHECK_ID,
    }
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields=audit,
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
    )


def main() -> int:
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
