"""Conceptual CLI spellings mapped to the registered adapter.

Workers reach for names that describe the outcome rather than the
registered grammar. The unknown-subcommand handler consults this table
before fuzzy did-you-mean so a known conceptual spelling prints the real
adapter and its one-line recipe. A new gap is one row.
"""

from __future__ import annotations

from typing import Sequence

from yoke_cli.commands.adapters.conflict_survey_status import (
    CONFLICT_SURVEY_STATUS_USAGE,
)
from yoke_cli.commands.adapters.dash import DASH_SURVEY_USAGE
from yoke_cli.commands.adapters.qa_read import (
    QA_REQUIREMENT_LIST_USAGE,
    QA_RUN_LIST_USAGE,
)
from yoke_cli.commands.adapters.session_control_messages import SAY_USAGE

# Conceptual argv prefix -> ((canonical cli form, one-line recipe), ...)
CONCEPTUAL_CLI_NAMES: dict[tuple[str, ...], tuple[tuple[str, str], ...]] = {
    ("qa", "evidence", "list"): (
        ("yoke qa requirement list", QA_REQUIREMENT_LIST_USAGE),
        ("yoke qa run list", QA_RUN_LIST_USAGE),
    ),
    ("claims", "path", "survey"): (
        ("yoke direct-workflow dash survey", DASH_SURVEY_USAGE),
        ("yoke direct-workflow conflict-survey status", CONFLICT_SURVEY_STATUS_USAGE),
    ),
    ("messages", "send"): (("yoke say", SAY_USAGE),),
}

_HELP_TOKENS = frozenset(("-h", "--help", "help"))


def _command_tokens(argv: Sequence[str]) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in argv:
        if token in _HELP_TOKENS or token.startswith("-"):
            break
        tokens.append(token)
    return tuple(tokens)


def conceptual_cli_hint(argv: Sequence[str]) -> str | None:
    """Return a did-you-mean block for a known conceptual spelling, or None."""
    tokens = _command_tokens(argv)
    for length in range(len(tokens), 0, -1):
        targets = CONCEPTUAL_CLI_NAMES.get(tokens[:length])
        if targets is None:
            continue
        lines: list[str] = []
        for cli_form, recipe in targets:
            lines.append(f"Did you mean `{cli_form}`?")
            lines.append(f"  {recipe}")
        return "\n".join(lines)
    return None
