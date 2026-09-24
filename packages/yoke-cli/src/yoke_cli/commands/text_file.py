"""Small argparse helpers for text-or-file CLI inputs."""

from __future__ import annotations

import argparse
import sys


def add_text_file_pair(
    group: argparse._MutuallyExclusiveGroup,
    text_flag: str,
    file_flag: str,
    *,
    dest: str,
    help_text: str = "Literal text value.",
    file_help: str = "Read the text value from a file.",
) -> None:
    group.add_argument(text_flag, dest=dest, help=help_text)
    group.add_argument(file_flag, dest=f"{dest}_file", help=file_help)


def add_stdin_flag(
    group: argparse._MutuallyExclusiveGroup,
    *,
    help_text: str = "Read the text value from stdin.",
) -> None:
    group.add_argument("--stdin", action="store_true", help=help_text)


def resolve_text_file(value: str | None, file_path: str | None, flag: str) -> str | None:
    if not file_path:
        return value
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise ValueError(f"cannot read {flag}: {exc}") from exc


def resolve_one_text_source(
    *,
    positional: str | None,
    file_path: str | None,
    stdin: bool,
    positional_label: str,
    file_flag: str,
    require_nonblank: bool = False,
) -> str:
    selected = sum(bool(item) for item in (positional, file_path, stdin))
    if selected > 1:
        raise ValueError(
            f"pass exactly one of {positional_label}, {file_flag}, or --stdin"
        )
    if stdin:
        text = sys.stdin.read()
        source = "--stdin"
    elif file_path:
        text = resolve_text_file(None, file_path, file_flag)
        text = text if text is not None else ""
        source = file_flag
    elif positional:
        text = positional
        source = positional_label
    else:
        raise ValueError(
            f"{positional_label}, {file_flag}, or --stdin is required"
        )
    if require_nonblank and not text.strip():
        raise ValueError(
            f"{source} supplied no instruction; provide nonblank text via "
            f"{positional_label}, {file_flag}, or --stdin"
        )
    return text


def resolve_optional_text_source(
    *,
    value: str | None,
    file_path: str | None,
    stdin: bool,
    text_flag: str,
    file_flag: str,
) -> str | None:
    selected = sum(bool(item) for item in (value, file_path, stdin))
    if selected == 0:
        return None
    return resolve_one_text_source(
        positional=value,
        file_path=file_path,
        stdin=stdin,
        positional_label=text_flag,
        file_flag=file_flag,
    )


__all__ = [
    "add_stdin_flag",
    "add_text_file_pair",
    "resolve_one_text_source",
    "resolve_optional_text_source",
    "resolve_text_file",
]
