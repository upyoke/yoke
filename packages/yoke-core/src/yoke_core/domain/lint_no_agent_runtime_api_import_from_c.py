"""PreToolUse Bash hook: refuse direct Yoke imports in ``python -c`` one-liners.

Agents that reach for ``python3 -c "from yoke_core.domain.yoke_function_dispatch
import dispatch; dispatch(...)"`` are using a fallback shape for an operation
Yoke already exposes as a CLI adapter or function-call surface. The
fallback is brittle (no claim-aware gates, no telemetry, no help text) and
shows up daily in live session transcripts.

Detection: a Bash command containing ``python``/``python3`` ``-c`` followed
by a quoted body that imports a Yoke-owned implementation symbol and is not
classifiable as a conservative read-only inspection probe. Post package-split surfaces include ``yoke_core.*``,
``yoke_cli.*``, and ``yoke_harness.*``; transitional legacy surfaces
include ``runtime.api.*``, ``runtime.harness.*``, and ``runtime.agents.*``.

Allowed shapes the lint stays out of:

* ``yoke <subcommand> ...`` — canonical agent shape (``items get``,
  ``claims work acquire``, ``lifecycle transition``, etc.; run
  ``yoke --help`` for the grouped catalog).
* ``python3 -m yoke_core.cli.db_router ...`` — operator-debug fallback
  inside a Yoke checkout (for function ids not yet wrapped by the ``yoke`` CLI).
* ``python3 -c "import json"`` — stdlib imports, no runtime.* reach-in.
* ``python3 -c "from collections import defaultdict"`` — same.
* ``python3 path/to/script.py`` — file invocation, not ``-c``.

Mode pinned by the project-local ``.yoke/lint-config`` guard key
``lint_no_agent_runtime_api_import_from_c`` (``warn`` records audit
only; ``deny`` blocks). There is no live machine-config key
``lint_agent_cli_contract_mode``. Suppression token
``# lint:no-agent-runtime-import-check`` on the Bash command body is
recorded as audit evidence only — the rule still denies in ``deny`` mode.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import List, Optional, Tuple

from yoke_core.domain.lint_no_agent_runtime_api_import_from_c_messages import (
    format_reason,
)
from yoke_core.domain.lint_no_agent_runtime_api_import_from_c_readonly import (
    is_read_only_import_probe,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-no-agent-runtime-api-import-from-c"
HOOK_NAME = "lint-no-agent-runtime-api-import-from-c"
SUPPRESSION_TOKEN = "# lint:no-agent-runtime-import-check"

_FORBIDDEN_IMPORT_PREFIX_RE = (
    r"(?:"
    r"yoke_core(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_cli(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_harness(?:\.[A-Za-z_][\w]*)*|"
    r"runtime(?:\.(?:api|harness|agents)(?:\.[A-Za-z_][\w]*)*)?"
    r")"
)
_FORBIDDEN_IMPORT_RE = re.compile(
    rf"(?:^|;|\s)(?:"
    rf"from\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\s+import\b|"
    rf"import\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\b"
    rf")"
)
_PYTHON_TOKEN_RE = re.compile(r"^python(?:3(?:\.\d+)?)?$")
#: The tokens immediately ahead of an interpreter that ``yoke dev run --``
#: wraps. Source-dev doctrine mandates that wrapper for lane source, so the
#: interpreter it launches is the sanctioned shape rather than a reach-in.
_SOURCE_RUN_PREFIX = ["dev", "run", "--"]


def _is_registered_source_run(tokens: List[str], python_index: int) -> bool:
    """True when ``yoke dev run --`` launches the interpreter at *python_index*.

    The exemption belongs to one invocation, not to the command body. Reading
    it off the body's LINES recognised only a single-line invocation, so the
    same wrapper was refused whenever its ``-c`` payload spanned lines or
    another command ran ahead of it — and, in the other direction, a wrapper
    at the start of the body exempted an unwrapped reach-in further along.
    """
    start = python_index - len(_SOURCE_RUN_PREFIX) - 1
    if start < 0:
        return False
    return (
        os.path.basename(tokens[start]) == "yoke"
        and tokens[start + 1 : python_index] == _SOURCE_RUN_PREFIX
    )


def _extract_tool_name(payload: dict) -> str:
    for k in ("tool_name", "toolName"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _read_mode(payload: object | None = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config).
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_no_agent_runtime_api_import_from_c",
        payload,
    )


def _iter_python_c_bodies(command: str):
    """Yield ``(ordinal, interpreter, body)`` per ``python(3)? -c`` invocation.

    Uses ``shlex.split`` for argument-aware tokenisation so the body is
    extracted post-shell-quoting. Returns the literal quoted body so the
    caller can scan it for ``runtime.*`` imports. An invocation the
    ``yoke dev run --`` wrapper launches is skipped, because that wrapper is
    the sanctioned way to run this checkout's own source.

    ``ordinal`` counts interpreter invocations from 1 across the whole
    command, so a refusal can say which one of a compound command it means.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return
    n = len(tokens)
    ordinal = 0
    for i, tok in enumerate(tokens):
        base = os.path.basename(tok)
        if not _PYTHON_TOKEN_RE.match(base):
            continue
        ordinal += 1
        if _is_registered_source_run(tokens, i):
            continue
        for j in range(i + 1, n):
            arg = tokens[j]
            if arg == "-c" and j + 1 < n:
                yield ordinal, tok, tokens[j + 1]
                break
            if arg.startswith("-") and arg not in (
                "-W",
                "-X",
                "-O",
                "-OO",
                "-u",
                "-q",
                "-v",
            ):
                if arg == "-m" or arg == "--":
                    break
                continue
            if not arg.startswith("-"):
                break


def _matched_import(body: str) -> str:
    """Return the import statement this rule matched, or ``""``."""
    match = _FORBIDDEN_IMPORT_RE.search(body)
    if match is None:
        return ""
    tail = body[match.start() :].lstrip("; \t\n")
    return tail.splitlines()[0].strip() if tail else ""


def _body_imports_runtime(body: str) -> bool:
    return bool(_FORBIDDEN_IMPORT_RE.search(body))


def _format_reason(
    suppression_seen: bool,
    mode: str,
    matched: str = "",
    ordinal: int = 0,
    interpreter: str = "",
) -> str:
    return format_reason(
        suppression_token=SUPPRESSION_TOKEN,
        suppression_seen=suppression_seen,
        mode=mode,
        matched=matched,
        ordinal=ordinal,
        interpreter=interpreter,
    )


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    """Apply the rule; return ``(mode, reason, outcome)`` when denying/warning."""
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    hit = False
    matched = ""
    ordinal = 0
    interpreter = ""
    for ordinal, interpreter, body in _iter_python_c_bodies(command):
        if _body_imports_runtime(body) and not is_read_only_import_probe(body):
            hit = True
            matched = _matched_import(body)
            break
    # The verdict is the match, never the message: deriving it from the
    # formatted text would let an empty helper result allow a reach-in.
    if not hit:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(suppression_seen, mode, matched, ordinal, interpreter)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return (mode, reason, outcome)


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event
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
    """Typed entry — pure shape parse, no subprocess fan-out."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
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
