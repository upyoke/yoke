"""Small argparse helpers for ``--text`` / ``--text-file`` pairs."""

from __future__ import annotations

import argparse


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


def resolve_text_file(value: str | None, file_path: str | None, flag: str) -> str | None:
    if not file_path:
        return value
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise ValueError(f"cannot read {flag}: {exc}") from exc


__all__ = ["add_text_file_pair", "resolve_text_file"]
