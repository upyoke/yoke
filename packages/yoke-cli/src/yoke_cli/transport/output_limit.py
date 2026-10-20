"""Atomic CLI read output bounds and explicit whole-answer opt-in."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

from yoke_contracts.registered_reads import READ_FUNCTION_IDS

# One default budget for rendered human and structured replies.
REPLY_LIMIT_BYTES = 4_000
_FULL_OUTPUT = ContextVar("full_read_output", default=False)
_READ_FUNCTION = ContextVar("registered_read_function", default=None)


@contextmanager
def read_output_scope(args: list[str], function: str | None = None) -> Iterator[None]:
    read_token = _READ_FUNCTION.set(function)
    token = _FULL_OUTPUT.set(
        "--full" in args[: args.index("--")] if "--" in args else "--full" in args
    )
    try:
        yield
    finally:
        _FULL_OUTPUT.reset(token)
        _READ_FUNCTION.reset(read_token)


def output_exceeds_limit(
    function: str, stdout: str, stderr: str, *, full: bool = False
) -> bool:
    return (
        not (full or _FULL_OUTPUT.get())
        and len((stdout + stderr).encode("utf-8")) > REPLY_LIMIT_BYTES
    )


def reply_exceeds_limit(text: str) -> bool:
    return len(text.encode("utf-8")) > REPLY_LIMIT_BYTES


def full_output_requested() -> bool:
    return _FULL_OUTPUT.get()


def registered_read_requested() -> bool:
    return _READ_FUNCTION.get() in READ_FUNCTION_IDS


def read_recovery(function: str) -> str:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    forms = [
        tokens for tokens, (name, _) in SUBCOMMAND_REGISTRY.items() if name == function
    ]
    tokens = (
        min(forms, key=lambda value: (len(value), value))
        if forms
        else tuple(function.replace("_", "-").split("."))
    )
    command = "yoke " + " ".join(tokens)
    if function not in READ_FUNCTION_IDS:
        return (
            "The operation already ran. Read the saved response.result before "
            f"repeating it; {command} --help names its result inspection recipe."
        )
    return (
        f"Narrow {command} with its field/filter flags or a smaller --limit "
        f"where supported; run {command} --help for the exact recipe, "
        f"or add --full to request the entire answer explicitly."
    )
