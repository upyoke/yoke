"""Flag-named title and spec sources for item filing."""

from __future__ import annotations

import argparse
import sys

from yoke_cli.commands.text_file import resolve_text_file


def add_create_text_args(parser: argparse.ArgumentParser) -> None:
    # Positional words are captured only so they can refuse by name.
    parser.add_argument("positional", nargs="*", help=argparse.SUPPRESS)
    title = parser.add_mutually_exclusive_group()
    title.add_argument("--title", help="Item title text.")
    title.add_argument("--title-file", help="Read title from this UTF-8 file.")
    spec = parser.add_mutually_exclusive_group()
    spec.add_argument("--spec-file", help="Read spec from this UTF-8 file.")
    spec.add_argument("--stdin", action="store_true", help="Read spec from stdin.")


def positional_refusal(command: str, workflow_flag: str) -> str:
    return (
        f"ITEM_TEXT_POSITIONAL_RETIRED: {command} takes no positional "
        "arguments, so a file path is never stored as title or spec text. Use "
        f"{command} --title TEXT{workflow_flag} --spec-file PATH (or --stdin); "
        "--title-file PATH reads the title from a file."
    )


def resolve_create_text(parsed: argparse.Namespace, shortcut: str | None, command: str):
    if parsed.positional:
        workflow_flag = "" if shortcut else " --workflow W"
        raise ValueError(positional_refusal(command, workflow_flag))
    workflow = shortcut or parsed.workflow
    if not workflow:
        raise ValueError("WORKFLOW_REQUIRED: add --workflow W")
    try:
        title = resolve_text_file(parsed.title, parsed.title_file, "--title-file")
        if parsed.stdin:
            spec = sys.stdin.read()
        else:
            spec = resolve_text_file(None, parsed.spec_file, "--spec-file")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(
            f"ITEM_TEXT_SOURCE_INVALID: {exc}. Use --title TEXT or "
            "--title-file PATH for title and --spec-file PATH or --stdin for spec."
        ) from exc
    if not title or not title.strip():
        raise ValueError(
            "TITLE_REQUIRED: add a nonblank --title TEXT or --title-file PATH"
        )
    if not (spec or "").strip():
        raise ValueError(
            "SPEC_REQUIRED: an item is created together with its spec. Write "
            "the agreed outcome to a file and add --spec-file PATH, or pipe it "
            "with --stdin; refinement adds detail later."
        )
    return title.strip(), workflow, spec
