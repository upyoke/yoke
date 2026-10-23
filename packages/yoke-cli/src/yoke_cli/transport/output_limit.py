"""Atomic CLI read output bounds and explicit whole-answer opt-in."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

from yoke_contracts.registered_reads import READ_FUNCTION_IDS

from yoke_contracts.read_detail import REPLY_LIMIT_BYTES

_FULL_OUTPUT = ContextVar("full_read_output", default=False)
_READ_FUNCTION = ContextVar("registered_read_function", default=None)
_READ_PARSER: ContextVar[argparse.ArgumentParser | None] = ContextVar(
    "registered_read_parser", default=None
)

_PROJECTION = {"fields", "field", "include", "section", "detail", "view"}
_LIMIT = {"limit", "page_size", "display_limit", "lines"}
_PAGING = {"offset", "cursor", "page"}
_NOT_NARROWING = {
    "help", "full", "json", "session_id", "project", "config", "stdin",
    "output", "output_file", "format", "timeout", "wait",
}


@contextmanager
def read_output_scope(args: list[str], function: str | None = None) -> Iterator[None]:
    read_token = _READ_FUNCTION.set(function)
    parser_token = _READ_PARSER.set(None)
    token = _FULL_OUTPUT.set(
        "--full" in args[: args.index("--")] if "--" in args else "--full" in args
    )
    try:
        yield
    finally:
        _FULL_OUTPUT.reset(token)
        _READ_FUNCTION.reset(read_token)
        _READ_PARSER.reset(parser_token)


def output_exceeds_limit(
    function: str, stdout: str, stderr: str, *, full: bool = False
) -> bool:
    return (
        function in READ_FUNCTION_IDS
        and not (full or _FULL_OUTPUT.get())
        and len((stdout + stderr).encode("utf-8")) > REPLY_LIMIT_BYTES
    )


def full_output_requested() -> bool:
    return _FULL_OUTPUT.get()


def registered_read_requested() -> bool:
    return _READ_FUNCTION.get() in READ_FUNCTION_IDS


def record_read_parser(parser: argparse.ArgumentParser) -> None:
    """Remember the parser this read parsed with, for its recovery hint."""
    _READ_PARSER.set(parser)


def narrowing_flags(parser: argparse.ArgumentParser) -> dict[str, list[str]]:
    """Group the parser's real narrowing arguments by kind."""
    groups: dict[str, list[str]] = {
        "fields": [], "filters": [], "limit": [], "paging": []
    }
    for action in parser._actions:
        if not action.option_strings:
            if action.dest in _PROJECTION:
                groups["fields"].append(action.metavar or action.dest.upper())
            continue
        if action.dest in _NOT_NARROWING:
            continue
        flag = max(action.option_strings, key=len)
        kind = (
            "fields" if action.dest in _PROJECTION
            else "limit" if action.dest in _LIMIT
            else "paging" if action.dest in _PAGING
            else "filters" if action.nargs != 0
            else None
        )
        if kind:
            groups[kind].append(flag)
    return {kind: flags for kind, flags in groups.items() if flags}


def read_recovery(function: str) -> str:
    """Teach the narrowing flags this read's parser really has."""
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
    parser = _READ_PARSER.get()
    if parser is None:
        return f"Run {command} --help to find how to narrow this read."
    groups = narrowing_flags(parser)
    named = "; ".join(f"{kind} {', '.join(flags)}" for kind, flags in groups.items())
    narrow = (
        f"Narrow {command} with its {named}"
        if named
        else f"{command} has no narrowing flags"
    )
    full = any("--full" in action.option_strings for action in parser._actions)
    return (
        f"{narrow}; run {command} --help for the exact recipe"
        + (", or add --full to request the entire answer explicitly." if full else ".")
    )
