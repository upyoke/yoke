"""PreToolUse Bash lint: block hand-quoted JSON / shell-soup function calls.

Three structural shapes (full prose in
:mod:`lint_shell_quoted_function_payload_messages`): hand-quoted JSON
payload to ``service_client``; registry-covered Yoke CLI wrapped with
shell choreography; and invocations in a known Yoke CLI domain whose
subcommand path is not a registered function-call adapter.

Allowed shapes the lint stays out of (designed-in adapter use): read-shape
adapters wrapped only by read-only shell shapes (S2); write-shape adapters
with canonical ``cat <free-path-file> | adapter --stdin`` upstream (the
file-to-stdin pattern every ``--stdin`` adapter is designed for); write-shape
adapters with read-only downstream wrapping (``| tail -N``, ``| head -N``,
``| jq ...``, free-path redirects — the write completed before the consumer
ran). ``--help`` short-circuits (S1). Outer-token scanning (S9) keeps the
adapter substring detection out of quoted / heredoc bodies. Subcommand-path
extraction (S10) stops at the first unquoted shell-syntax boundary. Bypass:
``# lint:no-shell-json-payload-check`` is audit-only.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_shell_quoted_function_payload_classify import (
    extract_subcommand_path,
    is_best_effort_wrapping,
    is_help_invocation,
    is_read_shape_function,
    is_read_wrapping,
    is_substantive_read_wrapping,
    is_write_output_consumer_only,
    mktemp_bound_vars,
    strip_safe_cat_stdin_source,
    tokenize_outer_command,
)
from yoke_core.domain.lint_shell_quoted_function_payload_messages import (
    build_adapter_index,
    build_choreography_remediation,
    build_domain_remediation,
    build_payload_remediation,
    resolve_mode as _resolve_mode,
)
from yoke_core.domain.lint_shell_quoted_function_payload_skill import (
    skill_orchestrated_note,
)
from yoke_core.domain.lint_shell_quoted_function_payload_wrapping_variants import (
    NO_CONSUMER_ALLOWANCE_FUNCTIONS as _NO_CONSUMER_ALLOWANCE_FUNCTIONS,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


_BYPASS_TOKEN = "# lint:no-shell-json-payload-check"

# Hand-quoted JSON payload to service_client.
_PRINTF_PIPE_PAYLOAD_RE = re.compile(
    r"\bprintf\b[^|\n]*?['\"]\s*\{.*?\}\s*['\"][^|\n]*?\|\s*"
    r"python3?\s+-m\s+(?:runtime\.api|yoke_core\.api)\.service_client\b[^\n]*?--payload\b",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_JSON_PAYLOAD_RE = re.compile(
    r"\bpython3?\s+-m\s+(?:runtime\.api|yoke_core\.api)\.service_client\b[^\n]*?"
    r"--payload\s+['\"]\s*\{",
    re.IGNORECASE,
)

_CHOREOGRAPHY_TOKENS: Tuple[str, ...] = (
    "2>&1", "; echo $?", "&& echo $?", "|", "$(",
)
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?\w+['\"]?")
_VAR_CAPTURE_RE = re.compile(r"\b\w+=\$\(\s*python3?")

_SHELL_BOUNDARY_TOKENS = frozenset({"|", "&&", ";", "&", "||"})

# Adapter index built at import time. Maps ``"<module> <sub-path>" ->
# function_id`` plus a sorted-sub-paths-per-module map for the
# domain-level remediation. Longest module first guards prefix matches.
_ADAPTER_INDEX, _REGISTERED_SUBS_BY_MODULE = build_adapter_index()
_MODULES_BY_LENGTH = tuple(
    sorted(_REGISTERED_SUBS_BY_MODULE.keys(), key=len, reverse=True)
)


@dataclass
class _RegisteredHit:
    adapter_key: str
    function_id: str
    command_tail: str = ""


@dataclass
class _DomainOnlyHit:
    module: str
    command_tail: str


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    for candidate in (tool_input.get("command"), tool_input.get("cmd"), payload.get("command")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


def _has_hand_quoted_json_payload(command: str) -> bool:
    return bool(_PRINTF_PIPE_PAYLOAD_RE.search(command)
        or _INLINE_JSON_PAYLOAD_RE.search(command))


def _collect_sub_tokens(rest_tokens: List[str]) -> List[str]:
    """Consume contiguous candidate subcommand tokens (no flags, no
    placeholders, no shell-boundary tokens, no path/expansion tokens)."""
    out: List[str] = []
    for tok in rest_tokens:
        if not tok or tok.startswith("-") or tok.startswith("YOK-"):
            break
        if "/" in tok or tok in _SHELL_BOUNDARY_TOKENS:
            break
        if "(" in tok or ")" in tok or "$" in tok:
            break
        out.append(tok)
    return out


def _find_module_in_command(command: str) -> Optional[Tuple[str, str]]:
    """Locate ``python(3) -m <module>`` for the longest known module.

    Outer tokens only (S9): quoted strings, heredoc bodies, and
    ``$(...)`` substitutions are opaque. Returns ``(module, tail)`` where
    ``tail`` is everything after the matched ``python -m <module>``.
    """
    outer_tokens = tokenize_outer_command(command)
    for module in _MODULES_BY_LENGTH:
        for prefix_tokens in (
            ("python3", "-m", module),
            ("python", "-m", module),
        ):
            if len(outer_tokens) < len(prefix_tokens):
                continue
            joined = " ".join(prefix_tokens)
            for start in range(len(outer_tokens) - len(prefix_tokens) + 1):
                window = outer_tokens[start:start + len(prefix_tokens)]
                if window == list(prefix_tokens):
                    idx = command.find(joined)
                    if idx >= 0:
                        return module, command[idx + len(joined):]
    return None


def _find_registry_covered_adapter(
    command: str,
) -> Optional[_RegisteredHit | _DomainOnlyHit]:
    """Return the lint-relevant adapter hit, or ``None``.

    Falls back to a domain-only hit when the module is known but no
    subcommand path matches a registered adapter key.
    """
    located = _find_module_in_command(command)
    if located is None:
        return None
    module, tail = located
    sub_path = extract_subcommand_path(tail)
    try:
        rest_tokens = shlex.split(sub_path)
    except ValueError:
        rest_tokens = sub_path.split()
    sub_tokens = _collect_sub_tokens(rest_tokens)
    for n in range(len(sub_tokens), -1, -1):
        key = " ".join([module, *sub_tokens[:n]]).rstrip()
        if key in _ADAPTER_INDEX:
            return _RegisteredHit(
                adapter_key=key,
                function_id=_ADAPTER_INDEX[key],
                command_tail=sub_path,
            )
    return _DomainOnlyHit(module=module, command_tail=sub_path)


def _has_shell_choreography(command: str) -> bool:
    if _HEREDOC_RE.search(command):
        return True
    if any(token in command for token in _CHOREOGRAPHY_TOKENS):
        return True
    return bool(_VAR_CAPTURE_RE.search(command))


def evaluate_command(command: str) -> Optional[str]:
    """Return a denial reason when *command* matches a banned shape.

    Triggers in order: hand-quoted JSON payload; registry-covered
    adapter wrapped with non-permitted choreography (precise function
    id); known-domain invocation with unregistered subcommand path
    (domain-level copy). ``--help`` short-circuits before scan (S1).
    """
    if not command or _BYPASS_TOKEN in command or is_help_invocation(command):
        return None
    if _has_hand_quoted_json_payload(command):
        return build_payload_remediation()

    hit = _find_registry_covered_adapter(command)
    if hit is None or not _has_shell_choreography(command):
        return None

    located = _find_module_in_command(command)
    tail = located[1] if located else ""
    mvars = mktemp_bound_vars(command)
    upstream = _has_upstream_choreography(command, located, mvars, tail)
    if isinstance(hit, _RegisteredHit):
        if not upstream:
            if is_read_shape_function(hit.function_id):
                if is_read_wrapping(tail, mktemp_vars=mvars):
                    return None
            elif (is_best_effort_wrapping(tail, mktemp_vars=mvars)
                  or (hit.function_id not in _NO_CONSUMER_ALLOWANCE_FUNCTIONS
                      and is_write_output_consumer_only(tail, mktemp_vars=mvars))):
                return None
        return build_choreography_remediation(hit.adapter_key, hit.function_id)
    # _DomainOnlyHit: require SUBSTANTIVE read wrapping — bare ``2>&1`` /
    # lone status probes do not qualify.
    if not upstream and is_substantive_read_wrapping(tail, mktemp_vars=mvars):
        return None
    return build_domain_remediation(
        module=hit.module,
        command_tail=hit.command_tail,
        registered_subs=_REGISTERED_SUBS_BY_MODULE.get(hit.module, []),
    )


_UPSTREAM_CHOREOGRAPHY_TOKENS: Tuple[str, ...] = (
    "|", "&&", "||", ";", "$(", "<<", "2>&1",
)
_UPSTREAM_MKTEMP_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)=\$\(\s*mktemp[^)]*\)\s*"
)


def _has_upstream_choreography(
    command: str,
    located: Optional[Tuple[str, str]],
    mktemp_vars: frozenset[str],
    tail: str = "",
) -> bool:
    if located is None:
        return False
    module = located[0]
    idx = command.find(f"-m {module}")
    if idx <= 0:
        return False
    prefix = _strip_safe_mktemp_assignments(command[:idx], mktemp_vars)
    if "--stdin" in tail:
        prefix = strip_safe_cat_stdin_source(prefix)
    return any(tok in prefix for tok in _UPSTREAM_CHOREOGRAPHY_TOKENS)


def _strip_safe_mktemp_assignments(
    prefix: str, mktemp_vars: frozenset[str],
) -> str:
    return _UPSTREAM_MKTEMP_RE.sub(
        lambda m: "" if m.group("name") in mktemp_vars else m.group(0),
        prefix,
    )


def _emit_denial(payload: dict, reason: str, *, outcome: str = "denied") -> None:
    """Best-effort ``HarnessToolCallDenied`` audit event."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    _s = lambda v: v if isinstance(v, str) else ""  # noqa: E731
    try:
        emit_denial_event(
            hook="lint-shell-quoted-function-payload", tool="Bash",
            check_id="shell_quoted_function_payload", reason=reason,
            session_id=_s(payload.get("session_id")),
            tool_use_id=_s(payload.get("tool_use_id")),
            turn_id=_s(payload.get("turn_id") or payload.get("message_id")),
            command_snippet=_extract_command(payload), outcome=outcome)
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Wraps :func:`evaluate_command` + bypass-token audit."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    command = _extract_command(payload)
    mode = _resolve_mode(payload)
    if _BYPASS_TOKEN in command:
        if evaluate_command(command.replace(_BYPASS_TOKEN, "")):
            _emit_denial(payload,
                "[outcome=suppression_attempted] shell-quoted function "
                "payload lint suppressed via token",
                outcome="suppression_attempted")
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = evaluate_command(command)
    if reason is None:
        note = skill_orchestrated_note(command)
        if note:
            _emit_denial(payload, note, outcome="warn")
            return HookDecision(outcome=Outcome.WARN, message=note, audit_fields={"note": note})
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = append_field_note_footer(reason, rule_id="lint-shell-quoted-function-payload")
    if mode == "warn":
        _emit_denial(payload, reason, outcome="warn")
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    envelope = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}})
    _emit_denial(payload, reason)
    return HookDecision(outcome=Outcome.DENY, message=envelope,
        audit_fields={"reason": reason, "audit_outcome": "denied"},
        block=True, next=Next.STOP)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload, tool_name="Bash",
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None)


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


__all__ = ["evaluate", "evaluate_command", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
