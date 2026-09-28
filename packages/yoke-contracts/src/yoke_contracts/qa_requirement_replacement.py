"""The ``--replaces CASE_KEY=REQUIREMENT_ID`` operand every materializing CLI shares.

A corrected QA case declares, when it is materialized, the exact failed
requirement it replaces. The server resolves ``CASE_KEY`` among the cases that
materialization produced; the failed requirement keeps blocking, leaves the
execution roster, and is superseded once the corrected case records a passing
independent verdict.
"""

from __future__ import annotations

import argparse
from typing import Any

REPLACES_METAVAR = "CASE_KEY=REQUIREMENT_ID"

REPLACES_HELP = (
    "Declare that this materialization's corrected case CASE_KEY replaces the "
    "failed requirement REQUIREMENT_ID. The failed case stays blocking but is "
    "no longer captured or reviewed again; it is superseded automatically when "
    "the corrected case records a passing independent verdict, and keeps "
    "blocking with its own evidence if the correction fails. Repeatable; to "
    "correct a failed correction, name that failed correction's id."
)


def parse_replacement(value: str) -> dict[str, Any]:
    """Parse one operand into the ``replacements`` payload entry."""
    case_key, sep, requirement = str(value).rpartition("=")
    if not sep or not case_key.strip() or not requirement.strip().isdigit():
        raise ValueError(
            f"--replaces {value!r} is not {REPLACES_METAVAR}; name the corrected "
            "plan case key and the failed requirement id it replaces, e.g. "
            "--replaces desktop-review=32796"
        )
    return {"case_key": case_key.strip(), "requirement_id": int(requirement)}


def _argument(value: str) -> dict[str, Any]:
    try:
        return parse_replacement(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def add_replaces_argument(parser: argparse.ArgumentParser) -> None:
    """Register the repeatable ``--replaces`` flag on a materializing command."""
    parser.add_argument(
        "--replaces",
        action="append",
        default=[],
        type=_argument,
        metavar=REPLACES_METAVAR,
        help=REPLACES_HELP,
    )


__all__ = [
    "REPLACES_HELP",
    "REPLACES_METAVAR",
    "add_replaces_argument",
    "parse_replacement",
]
