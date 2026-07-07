"""PreToolUse Bash hook: deny writer-class commands from a cross-checkout cwd.

Closes the leak shape structurally. When ``$YOKE_BOUND_WORKSPACE``
is set (exported at SessionStart by the harness session-workspace helper)
and the Bash command is a writer-class tool whose execution cwd is *not*
under that workspace, the hook denies the call before the writer subprocess
runs.

Writer-class verbs caught today:

- ``pytest`` / ``python3 -m pytest`` (test-fixture writes were the leak vector)
- ``python3 -m yoke_core.domain.agents_render`` (the renderer CLI itself)
- ``python3 -m yoke_core.tools.run_tests`` (Yoke's generic test runner)

The mode (``warn`` audits without blocking, ``deny`` denies) is pinned by
the ``lint_workspace_cwd_match_mode`` key in machine config. Yoke dogfood
defaults to ``deny``. The suppression token ``# lint:no-workspace-cwd-check``
is recorded as ``outcome=suppression_attempted`` audit evidence and does NOT
unblock — symmetric with the path-claim guard's audit-only token shape.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is preserved
for legacy stdin shells; exit code is always ``0``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


CHECK_ID = "lint-workspace-cwd-match"
HOOK_NAME = "lint-workspace-cwd-match"
SUPPRESSION_TOKEN = "# lint:no-workspace-cwd-check"

BOUND_WORKSPACE_ENV_VAR = "YOKE_BOUND_WORKSPACE"

# Statement separators used by the path_claim_bash_guard sibling. Same shape
# so writer-class verbs anywhere in a compound command are detected.
_SEP_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
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


def _extract_command(payload: dict) -> str:
    for k in ("tool_input", "toolInput", "input"):
        ti = payload.get(k)
        if isinstance(ti, dict):
            for ck in ("command", "cmd"):
                v = ti.get(ck)
                if isinstance(v, str) and v:
                    return v
    v = payload.get("command")
    return v if isinstance(v, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for k in ("tool_name", "toolName"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _extract_cwd(payload: dict) -> str:
    for k in ("cwd", "workspace", "project_dir"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return os.getcwd()


def _read_mode(payload: object | None = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config).
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_workspace_cwd_match", payload)


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
    out: list[list[str]] = []
    for stmt in _SEP_RE.split(command or ""):
        if not stmt.strip():
            continue
        try:
            tokens = shlex.split(stmt, posix=True)
        except ValueError:
            continue
        tokens = _strip_env_prefix(tokens)
        if tokens:
            out.append(tokens)
    return out


def _is_under(target: str, root: str) -> bool:
    try:
        Path(target).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _format_reason(
    workspace: str, cwd: str, statement_tokens: list[str], suppression_seen: bool, mode: str,
) -> str:
    head = " ".join(statement_tokens[:6])
    suffix = ""
    if mode == "warn":
        suffix = "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        suffix = (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — the "
            "rule still denies. Run the command from the bound workspace, or use "
            "a command surface that names the target root explicitly."
        )
    body = (
        "BLOCKED: writer-class command invoked from a cross-checkout cwd.\n\n"
        f"Bound workspace: {workspace}\n"
        f"Current cwd:     {cwd}\n"
        f"Command shape:   {head}\n\n"
        "Remediation: re-run the command from the bound workspace (e.g. `git -C "
        f"{workspace} ...`, `python3 -m pytest --rootdir {workspace} ...`), "
        "or use a writer surface that takes an explicit `--target-root` / "
        "`YOKE_RENDER_TARGET_ROOT` anchor."
        f"{suffix}"
    )
    return append_field_note_footer(body, rule_id="lint-workspace-cwd-match")


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    """Apply rules; return ``(mode, reason, outcome)`` when denying/warning."""
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    workspace = os.environ.get(BOUND_WORKSPACE_ENV_VAR, "").strip()
    if not workspace:
        return None
    command = _extract_command(payload)
    if not command:
        return None
    cwd = _extract_cwd(payload)
    if not cwd:
        return None
    if _is_under(cwd, workspace):
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    for tokens in _statements(command):
        if not _matches_writer_verb(tokens):
            continue
        mode = _read_mode(payload)
        reason = _format_reason(workspace, cwd, tokens, suppression_seen, mode)
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    return None


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    sid = payload.get("session_id") or ""
    tu = payload.get("tool_use_id") or ""
    turn = payload.get("turn_id") or payload.get("message_id") or ""
    audit_reason = f"[mode={mode}] {reason}" if mode == "warn" else reason
    try:
        emit_denial_event(
            hook=HOOK_NAME,
            tool="Bash",
            check_id=CHECK_ID,
            reason=audit_reason,
            session_id=sid if isinstance(sid, str) else "",
            tool_use_id=tu if isinstance(tu, str) else "",
            turn_id=turn if isinstance(turn, str) else "",
            command_snippet=_extract_command(payload),
            outcome=outcome,
        )
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Reads ``$YOKE_BOUND_WORKSPACE``; no DB access."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd = payload.get("cwd")
    sid = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
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
        print(decision.message)
    return 0


# The static scan for direct ``_repo_root`` references lives in
# ``yoke_core.domain.lint_workspace_repo_root_scan`` so this module
# stays under the file-line authoring cap. The PreToolUse Bash hook here
# audits *outer* writer-class invocations from cross-checkout cwds; the
# scan helper there catches *inner* import/attribute references that
# never reach the Bash layer.


if __name__ == "__main__":
    sys.exit(main())
