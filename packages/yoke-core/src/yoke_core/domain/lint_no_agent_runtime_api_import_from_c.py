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

The guard always returns a deny; the hook runner's mode gate applies the
``.yoke/lint-config`` guard key ``lint_no_agent_runtime_api_import_from_c``
(``warn`` downgrades it to an audit-only row). Suppression token
``# lint:no-agent-runtime-import-check`` on the Bash command body is
recorded as audit evidence only — it does not unblock.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import re
import sys
from typing import List, Optional, Tuple

from yoke_core.domain.lint_no_agent_runtime_api_import_from_c_messages import (
    format_reason,
)
from yoke_core.domain.lint_no_agent_runtime_api_import_from_c_readonly import (
    is_read_only_import_probe,
)
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-no-agent-runtime-api-import-from-c"
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


def _is_registered_source_run(tokens: List[str], python_index: int) -> bool:
    """True when ``yoke ... dev run ... --`` launches the interpreter here.

    Source-dev doctrine mandates that wrapper for lane source, so the
    interpreter it launches is the sanctioned shape rather than a reach-in.
    The ``--`` must sit directly before the interpreter; walking back from it
    to the nearest ``yoke``, ``dev run`` must lie between. Global flags
    (``yoke --env prod-db-admin dev run --``) and run flags
    (``yoke dev run --lane /x --``) are allowed. ``tokens`` is one
    invocation's argv, so a wrapper in an earlier command never reaches it.

    The exemption belongs to one invocation, not to the command body. Reading
    it off the body's LINES recognised only a single-line invocation, so the
    same wrapper was refused whenever its ``-c`` payload spanned lines or
    another command ran ahead of it — and, in the other direction, a wrapper
    at the start of the body exempted an unwrapped reach-in further along.
    """
    dash = python_index - 1
    if dash < 0 or tokens[dash] != "--":
        return False
    for start in range(dash - 1, -1, -1):
        token = tokens[start]
        if os.path.basename(token) == "yoke":
            between = tokens[start + 1 : dash]
            return any(
                between[k : k + 2] == ["dev", "run"] for k in range(len(between))
            )
    return False


#: Commands that run the argv after them, so an interpreter there still runs.
_LAUNCHER_WORDS = frozenset(
    {"command", "env", "exec", "nice", "nohup", "run", "sudo", "timeout", "uv"}
)


def _interpreter_index(tokens: List[str]) -> Optional[int]:
    """Index of the interpreter this invocation runs, or ``None``.

    The command word, the word after a ``--`` that hands over an argv, or
    a word reached only through launcher words, their flags, durations and
    assignments. Any other word is an operand: ``rg 'python3 -c ...'``
    names no interpreter.
    """
    if "--" in tokens:
        after = tokens.index("--") + 1
        if after < len(tokens) and _PYTHON_TOKEN_RE.match(
            os.path.basename(tokens[after])
        ):
            return after
    for i, tok in enumerate(tokens):
        if _PYTHON_TOKEN_RE.match(os.path.basename(tok)):
            return i
        if not (
            tok in _LAUNCHER_WORDS
            or tok.startswith("-")
            or tok.replace(".", "").isdigit()
            or "=" in tok
        ):
            return None
    return None


def _iter_python_c_bodies(command: str | ShellParse):
    """Yield ``(ordinal, interpreter, body)`` per ``python(3)? -c`` invocation.

    Only an interpreter in command position runs: the shared quote-aware
    splitter yields each invocation's argv, and heredoc bodies are dropped
    first because they are stdin data for whatever command reads them, so
    prose that quotes an import one-liner is never an invocation. The body
    is the post-quoting ``-c`` argument. An invocation the
    ``yoke dev run --`` wrapper launches is skipped, because that wrapper is
    the sanctioned way to run this checkout's own source.

    ``ordinal`` counts interpreter invocations from 1 across the whole
    command, so a refusal can say which one of a compound command it means.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    ordinal = 0
    for segment in parsed.segments:
        tokens = list(segment.argv)
        i = _interpreter_index(tokens)
        if i is None:
            continue
        ordinal += 1
        if _is_registered_source_run(tokens, i):
            continue
        n = len(tokens)
        for j in range(i + 1, n):
            arg = tokens[j]
            if arg == "-c" and j + 1 < n:
                yield ordinal, tokens[i], tokens[j + 1]
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
    matched: str = "",
    ordinal: int = 0,
    interpreter: str = "",
) -> str:
    return format_reason(
        suppression_token=SUPPRESSION_TOKEN,
        suppression_seen=suppression_seen,
        matched=matched,
        ordinal=ordinal,
        interpreter=interpreter,
    )


def evaluate_payload(
    payload: dict, shell: Optional[ShellParse] = None
) -> Optional[Tuple[str, str]]:
    """Apply the rule; return ``(reason, audit_outcome)`` on a hit, else None.

    ``shell`` is the hook call's shared parse of the same command.
    """
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    hit = False
    matched = ""
    ordinal = 0
    interpreter = ""
    parsed = shell if shell is not None else parse_shell(command)
    for ordinal, interpreter, body in _iter_python_c_bodies(parsed):
        if _body_imports_runtime(body) and not is_read_only_import_probe(body):
            hit = True
            matched = _matched_import(body)
            break
    # The verdict is the match, never the message: deriving it from the
    # formatted text would let an empty helper result allow a reach-in.
    if not hit:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(suppression_seen, matched, ordinal, interpreter)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload, record.shell)
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
