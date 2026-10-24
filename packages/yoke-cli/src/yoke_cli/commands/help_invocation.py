"""Recognize print-only invocations before the shared hook runner dispatches."""

import shlex


def is_help_only_command(command: str) -> bool:
    """Keep operands, shell effects and forwarded commands in the guard chain."""
    if not any(flag in command for flag in ("-h", "--help", "--version")):
        return False
    if any(char in command for char in ";&|<>$`\n()"):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words:
        return False
    args = words[1:]
    if words[0].rsplit("/", 1)[-1] == "yoke":
        from yoke_cli.commands.command_tree import listed_routes
        from yoke_cli.commands.group_help import can_route_group

        prefix = tuple(arg for arg in args if not arg.startswith("-"))
        if prefix and prefix not in listed_routes() and not can_route_group(prefix):
            return False
        args = args[len(prefix):]
    return bool(args) and all(arg in {"-h", "--help", "--version"} for arg in args)
