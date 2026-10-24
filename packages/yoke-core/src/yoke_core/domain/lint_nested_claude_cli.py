"""Nested-Claude classifier for the Bash command policy hook.

A second Claude Code session started from inside a running one crashes the
parent, which is why the ``claude`` binary is refused at all. Only the Claude
family can nest, though: a Codex or Cursor agent that runs ``claude`` starts a
first session, and ``claude --help`` starts none at all. Matching the command
text alone therefore refuses callers that were never at risk — observed live
as ``claude --help`` denied inside Codex.

So the question this module answers is not "does the command say claude" but
"would running it nest a Claude session inside a Claude session". The caller's
harness family is the trusted half of that answer: over the https relay only
the client can see its own process tree, so the evaluating side reads the
family the relay already carried (:data:`CALLER_HARNESS_PAYLOAD_KEY`, stamped
from the request's executor) and falls back to its own ancestry walk for a
local universe, where the evaluating process IS the caller.

Ancestry that resolves to nothing is not an allowance: a caller Yoke cannot
identify may well be a Claude session, so unknown context keeps the refusal
and names the operator override.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterator, Mapping, Optional, Sequence

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_family_identity import (
    CLAUDE_FAMILY,
    nearest_harness_family,
)
from yoke_contracts.hook_runner.hook_guard_catalog import (
    NESTED_CLAUDE_CLI_CHECK_ID,
    NESTED_CLAUDE_CLI_GUARD,
)
from yoke_contracts.hook_runner.shell_parse import (
    ShellParse,
    parse_shell,
    strip_env_prefix,
)
from yoke_core.domain import lint_config

#: Payload key carrying the calling harness family across the relay split.
CALLER_HARNESS_PAYLOAD_KEY = "yoke_hook_caller_harness"

_NESTING_CONSEQUENCE = "Nested claude processes crash Claude Code sessions."
_AGENT_TOOL_RECOVERY = (
    "use the Agent tool for subagent dispatch. " + _NESTING_CONSEQUENCE
)
_OVERRIDE_RECOVERY = (
    f"Set {NESTED_CLAUDE_CLI_GUARD}=warn in .yoke/lint-config only for an "
    "operator-attended canary; that setting is independent of the "
    "DB-command guard, which keeps denying."
)

NESTED_CLAUDE_CLI_DENIAL = (
    "BLOCKED: Do not invoke claude as a CLI command from a Claude session "
    "— " + _AGENT_TOOL_RECOVERY
)
UNKNOWN_CALLER_CLAUDE_CLI_DENIAL = (
    "BLOCKED: claude CLI invoked from a caller Yoke cannot identify, so a "
    "nested Claude session cannot be ruled out. " + _NESTING_CONSEQUENCE + " "
    "Run it from a harness session Yoke registers, use a sessionless flag "
    "(-h, --help, --version), or: " + _OVERRIDE_RECOVERY
)


def resolve_caller_family(payload: object | None = None) -> Optional[str]:
    """Return the harness family driving this hook invocation, or ``None``.

    The relayed value wins: the evaluating server's own process tree names an
    API worker, never the caller. ``None`` means no family could be trusted —
    an operator terminal, CI, or a relayed request that carried no executor.
    """
    stated = (
        payload.get(CALLER_HARNESS_PAYLOAD_KEY)
        if isinstance(payload, Mapping)
        else None
    )
    if isinstance(stated, str) and stated.strip():
        try:
            return canonical_harness_id(stated)
        except ValueError:
            return None
    try:
        return nearest_harness_family()
    except Exception:  # noqa: BLE001 — a guard must never raise on context
        return None


def _opened_command(words: Sequence[str]) -> list[str]:
    """Words of a command opened by ``(``/``$(``, up to its closing ``)``."""
    closed: list[str] = []
    for word in words:
        closed.append(word.rstrip(")"))
        if word.endswith(")"):
            break
    return strip_env_prefix([word for word in closed if word])


def _commands_in(argv: Sequence[str], tokens: Sequence[str]) -> Iterator[list[str]]:
    """Yield the segment's own command and each ``$(...)`` it opens."""
    if argv and argv[0].startswith("("):
        yield _opened_command([argv[0].lstrip("("), *argv[1:]])
    elif argv:
        yield list(argv)
    for index, token in enumerate(tokens):
        for opened in token.split("$(")[1:]:
            yield _opened_command([opened, *tokens[index + 1:]])


def claude_invocations(command: str | ShellParse) -> list[list[str]]:
    """Return each command in ``command`` whose binary is ``claude``.

    Each entry is that command's own words, binary first. A word is the
    binary only in command position: first in a segment of the shared parse
    or just inside an opening ``(``/``$(``, past any ``VAR=value`` prefixes.
    Line continuations join and heredoc bodies are input, so a path argument
    such as ``runtime/harness/claude`` on a continued line is never read as a
    command. Text the shell cannot tokenize runs nothing, so it names no
    invocation.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    return [
        words
        for segment in parsed.segments
        for words in _commands_in(segment.argv, segment.tokens)
        if words and PurePosixPath(words[0]).name == "claude"
    ]


def nested_claude_cli_denial(
    words: Sequence[str],
    payload: object | None = None,
) -> Optional[str]:
    """Return the denial reason for one ``claude`` invocation, else ``None``.

    ``words`` is the invocation's own words, binary first. ``None`` means the
    invocation carries no nesting risk, or that the operator put this guard in
    ``warn``.
    """
    family = resolve_caller_family(payload)
    if family is not None and family != CLAUDE_FAMILY:
        return None
    try:
        mode = lint_config.resolve_mode_for_payload(
            NESTED_CLAUDE_CLI_GUARD,
            payload,
        )
    except Exception:  # noqa: BLE001 — an unreadable config stays strict
        mode = lint_config.DENY
    if mode == lint_config.WARN:
        return None
    if family == CLAUDE_FAMILY:
        return NESTED_CLAUDE_CLI_DENIAL
    return UNKNOWN_CALLER_CLAUDE_CLI_DENIAL


__all__ = [
    "CALLER_HARNESS_PAYLOAD_KEY",
    "NESTED_CLAUDE_CLI_CHECK_ID",
    "NESTED_CLAUDE_CLI_DENIAL",
    "NESTED_CLAUDE_CLI_GUARD",
    "UNKNOWN_CALLER_CLAUDE_CLI_DENIAL",
    "claude_invocations",
    "nested_claude_cli_denial",
    "resolve_caller_family",
]
