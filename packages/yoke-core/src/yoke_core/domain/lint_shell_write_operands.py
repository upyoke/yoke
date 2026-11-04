"""Write operands for copy commands and the local source runner."""

from pathlib import PurePath
from typing import Sequence

from yoke_core.domain.lint_session_cwd_host_command import _invokes


def source_run_argv(tokens: Sequence[str]) -> list[str]:
    """Expose the command executed locally by ``yoke dev run``."""
    if tokens and _invokes(PurePath(tokens[0]).name, tokens, ("dev", "run")):
        if "--" in tokens:
            return list(tokens[tokens.index("--") + 1 :])
    return list(tokens)


def copy_write_operands(args: Sequence[str]) -> list[str]:
    """Return an explicit target directory, or the last positional operand."""
    positionals = []
    for index, arg in enumerate(args):
        if arg == "--":
            positionals.extend(args[index + 1 :])
            break
        if arg.startswith("-t") and len(arg) > 2:
            return [arg[2:]]
        if arg == "--target-directory" or (
            arg.startswith("-") and not arg.startswith("--") and arg.endswith("t")
        ):
            return list(args[index + 1 : index + 2])
        if arg.startswith("--target-directory="):
            return [arg.split("=", 1)[1]]
        if arg != "-" and not arg.startswith("-"):
            positionals.append(arg)
    return positionals[-1:]
