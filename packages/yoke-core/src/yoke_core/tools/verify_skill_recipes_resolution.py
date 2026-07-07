"""Resolution helpers for ``verify_skill_recipes`` smoke dispatch."""

from __future__ import annotations

from yoke_cli.commands.registry import resolve
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_core.domain.function_authz_scope import is_explicit_client_local


_TOP_LEVEL = {"-h", "--help", "help", "-V", "--version", "version"}


def dispatch_needed(argv: list[str]) -> tuple[bool, str | None]:
    """Return ``(needs_dispatch, error)`` for a parsed recipe argv."""
    if not argv or argv[0] != "yoke":
        return False, "recipe does not start with 'yoke'"
    command_argv, globals_ok = _strip_global_flags(argv[1:])
    if not globals_ok:
        return False, "invalid global --env flag"
    if len(command_argv) == 1 and command_argv[0] in _TOP_LEVEL:
        return False, None
    try:
        _tokens, function_id, _adapter, _rest = resolve(command_argv)
    except KeyError:
        if resolve_tool_shaped(command_argv) is not None:
            return False, None
        return False, "unknown yoke subcommand"
    # Client-local / aggregate commands (status, env use, render,
    # templates.*, the project.install family, …) resolve to a registered
    # subcommand but route NO single function-call dispatch — they read or
    # write the caller's own machine/repo, or aggregate many reads, and
    # their exit code reflects machine state, not a recipe defect. The
    # smoke verifies they RESOLVE and stops there: dispatching them would
    # capture nothing (false "no dispatch captured") or argparse-fail a
    # bare reference-listing command name (false exit!=0).
    if is_explicit_client_local(function_id):
        return False, None
    return True, None


def _strip_global_flags(argv: list[str]) -> tuple[list[str], bool]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--env":
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                return argv, False
            i += 2
            continue
        if token.startswith("--env="):
            if not token.split("=", 1)[1].strip():
                return argv, False
            i += 1
            continue
        out.append(token)
        i += 1
    return out, True


__all__ = ["dispatch_needed"]
