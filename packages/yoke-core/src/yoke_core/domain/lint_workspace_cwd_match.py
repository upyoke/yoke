"""PreToolUse Bash hook: deny writer-class commands from a cross-checkout cwd.

Closes the leak shape structurally. When the ambient session holds one or
more active worktree claims and the Bash command is a writer-class tool whose
execution cwd is *not* under any claimed worktree, the hook denies the call
before the writer subprocess runs.

Writer-class verbs caught today:

- ``pytest`` / ``python3 -m pytest`` (test-fixture writes were the leak vector)
- ``python3 -m yoke_core.domain.agents_render`` (the renderer CLI itself)
- ``python3 -m yoke_core.tools.run_tests`` (Yoke's generic test runner)

The guard always returns a deny; the hook runner's mode gate applies the
``.yoke/lint-config`` guard key ``lint_workspace_cwd_match`` (``warn``
downgrades it to an audit-only row). The suppression token ``# lint:no-workspace-cwd-check``
is declared as ``audit_outcome=suppression_attempted`` for the hook runner's
audit row and does NOT unblock — symmetric with the path-claim guard's audit-only token shape.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is preserved
for legacy stdin shells; exit code is always ``0``.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import re
import sys
from pathlib import PurePath
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.command_workdir import command_execution_cwd
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    strip_heredoc_syntax,
)
from yoke_core.domain.lint_shell_target_tokens import (
    command_operand_tokens,
    shell_command_segments,
)
from yoke_core.domain.session_ambient_identity import session_id_from_hook_payload
from yoke_core.domain.workspace_authority import resolve_session_worktree_paths
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command


CHECK_ID = "lint-workspace-cwd-match"
SUPPRESSION_TOKEN = "# lint:no-workspace-cwd-check"

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ENV_OPTIONS_WITH_ARG = {"-u", "--unset", "-C", "--chdir"}


# Writer-class verbs. Each entry is the leading argv-after-env-prefix shape;
# detection consumes a leading ``python3 -m`` when needed.
_WRITER_VERBS = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("python", "-m", "yoke_core.domain.agents_render"),
    ("python3", "-m", "yoke_core.domain.agents_render"),
    ("python", "-m", "yoke_core.tools.run_tests"),
    ("python3", "-m", "yoke_core.tools.run_tests"),
)


def _strip_env_prefix(tokens: list[str]) -> list[str]:
    i = 0
    if tokens and tokens[0] == "env":
        i = 1
        while i < len(tokens) and tokens[i].startswith("-"):
            option = tokens[i]
            i += 1
            if option in _ENV_OPTIONS_WITH_ARG and i < len(tokens):
                i += 1
    while i < len(tokens) and _ENV_RE.match(tokens[i]):
        i += 1
    return tokens[i:]


def _matches_writer_verb(tokens: list[str]) -> bool:
    if not tokens:
        return False
    head = tokens[0].rsplit("/", 1)[-1]
    rest = tokens[1:]
    normalised = (head,) + tuple(rest[:2])
    for verb in _WRITER_VERBS:
        prefix = verb[: len(normalised)]
        if normalised[: len(verb)] == verb:
            return True
        if prefix == normalised and len(normalised) >= len(verb):
            return True
    return False


def _statements(command: str) -> list[list[str]]:
    """Return each invocation's argv, command word first.

    The shared quote-aware splitter keeps a quoted search pattern such as
    ``rg 'a|pytest|b'`` one operand, and heredoc bodies are data, so only a
    word in command position can name a writer.
    """
    out: list[list[str]] = []
    for segment in shell_command_segments(strip_heredoc_syntax(command or "")):
        tokens = _strip_env_prefix(command_operand_tokens(segment))
        if tokens:
            out.append(tokens)
    return out


def _is_under(target: str, root: str) -> bool:
    """Compare as written: both paths name the client's filesystem."""
    try:
        PurePath(os.path.normpath(target)).relative_to(os.path.normpath(root))
    except ValueError:
        return False
    return True


def _format_reason(
    workspace: str,
    cwd: str,
    statement_tokens: list[str],
    suppression_seen: bool,
) -> str:
    head = " ".join(statement_tokens[:6])
    suffix = ""
    if suppression_seen:
        suffix = (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — the "
            "rule still denies. Run the command from a claimed worktree, or use "
            "a command surface that names the target root explicitly."
        )
    body = (
        "BLOCKED: writer-class command invoked from a cross-checkout cwd.\n\n"
        f"Claimed worktrees: {workspace}\n"
        f"Current cwd:     {cwd}\n"
        f"Command shape:   {head}\n\n"
        "Remediation: re-run the command from a claimed worktree (e.g. `git -C "
        f"{workspace} ...`, `python3 -m pytest --rootdir {workspace} ...`), "
        "or use a writer surface that takes an explicit `--target-root` / "
        "`YOKE_RENDER_TARGET_ROOT` anchor."
        f"{suffix}"
    )
    return attach_check_id(body, check_id="lint-workspace-cwd-match")


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Apply rules; return ``(reason, audit_outcome)`` on a hit, else None."""
    if not isinstance(payload, dict):
        return None
    # The hook payload names the session; the evaluating process's own
    # environment belongs to whichever machine runs the chain.
    session_id = session_id_from_hook_payload(payload)
    if not session_id:
        return None
    workspaces = resolve_session_worktree_paths(session_id)
    if not workspaces:
        return None
    command = _extract_command(payload)
    if not command:
        return None
    # The call's declared workdir and any leading ``cd`` decide where the
    # writer runs, exactly as the shell will.
    cwd = command_execution_cwd(payload)
    if not cwd:
        return None
    if any(_is_under(cwd, workspace) for workspace in workspaces):
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    for tokens in _statements(command):
        if not _matches_writer_verb(tokens):
            continue
        reason = _format_reason(
            ", ".join(workspaces),
            cwd,
            tokens,
            suppression_seen,
        )
        return reason, "suppression_attempted" if suppression_seen else "denied"
    return None


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Reads active worktree claims through the live authority."""
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
    cwd = payload.get("cwd")
    sid = payload.get("session_id")
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


# The static scan for direct ``_repo_root`` references lives in
# ``yoke_core.domain.lint_workspace_repo_root_scan`` so this module
# stays under the file-line authoring cap. The PreToolUse Bash hook here
# audits *outer* writer-class invocations from cross-checkout cwds; the
# scan helper there catches *inner* import/attribute references that
# never reach the Bash layer.


if __name__ == "__main__":
    sys.exit(main())
