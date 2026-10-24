"""Remote-SSH Claude CLI classifier for the DB-command hook."""

from __future__ import annotations

from yoke_contracts.hook_runner.hook_guard_catalog import (
    REMOTE_CLAUDE_CLI_CHECK_ID,
)
from yoke_contracts.hook_runner.shell_parse import parse_shell, strip_env_prefix
from yoke_core.domain import lint_config

REMOTE_CLAUDE_DENIAL = (
    "BLOCKED: Remote SSH command invokes claude as a CLI. "
    f"Set {lint_config.REMOTE_CLAUDE_CLI_GUARD}=warn in .yoke/lint-config "
    "only for operator-attended remote smoke tests."
)


def remote_claude_cli_state(
    command: str,
    payload: object | None = None,
) -> tuple[bool, bool]:
    """Return ``(seen_remote_claude, softened_by_lint_config)``.

    ``command`` is the rule text's quote-blanked command, so it is parsed
    here rather than reusing the hook call's parse of the original text.
    Blanking can unbalance ``'\\''`` quoting; a statement shlex cannot read
    is then named by its first plain word.
    """
    parsed = parse_shell(command)
    programs = [
        segment.program for segment in parsed.segments if "claude" in segment.text
    ] + [
        (strip_env_prefix(statement.split()) or [""])[0].rsplit("/", 1)[-1]
        for statement in parsed.unparsed
        if "claude" in statement
    ]
    is_remote = bool(programs) and all(program == "ssh" for program in programs)
    if not is_remote:
        return False, False
    try:
        mode = lint_config.resolve_mode_for_payload(
            lint_config.REMOTE_CLAUDE_CLI_GUARD,
            payload,
        )
    except Exception:
        mode = lint_config.DENY
    return True, mode == lint_config.WARN


__all__ = [
    "REMOTE_CLAUDE_CLI_CHECK_ID",
    "REMOTE_CLAUDE_DENIAL",
    "remote_claude_cli_state",
]
