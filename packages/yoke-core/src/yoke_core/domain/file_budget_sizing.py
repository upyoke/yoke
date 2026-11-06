"""Machine-readable sizing fields carried by File Budget path entries."""

from __future__ import annotations

from dataclasses import dataclass
import re

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT
from yoke_core.domain.file_budget_paths import FILE_BUDGET_PATH_CHARS


FILE_BUDGET_REMEDIATION = (
    "Declare a File Budget as a dash list, with each path in backticks. "
    "Each row must include current N lines; remaining headroom M (350 minus N); "
    "at-or-over-limit: true|false (true when N >= 350). "
    "For new files use current 0 lines. List each generated copy as its own row. "
    "Include every path in the claim when path claims are enabled. "
    "Example row:\n"
    "- `src/example.py` — current 120 lines; remaining headroom 230; "
    "at-or-over-limit: false"
)


@dataclass(frozen=True)
class FileBudgetSizing:
    path: str
    current_line_count: int
    remaining_headroom: int
    at_or_over_limit: bool


def path_sizing_pattern(path: str | None = None) -> re.Pattern[str]:
    path_group = re.escape(path) if path is not None else rf"{FILE_BUDGET_PATH_CHARS}+"
    return re.compile(
        rf"`(?P<path>{path_group})`(?:(?!`)[\s\S])*?"
        r"\bcurrent\s+(?P<count>\d+)\s+lines?\s*;\s*"
        r"remaining\s+headroom\s+(?P<headroom>-?\d+)\s*;\s*"
        r"at-or-over-limit\s*:\s*(?P<at_limit>true|false)",
        re.IGNORECASE,
    )


def parse_file_budget_sizing(text: str) -> list[FileBudgetSizing]:
    return [
        FileBudgetSizing(
            path=match.group("path"),
            current_line_count=int(match.group("count")),
            remaining_headroom=int(match.group("headroom")),
            at_or_over_limit=match.group("at_limit").casefold() == "true",
        )
        for match in path_sizing_pattern().finditer(text or "")
    ]


def replacement_for_current_size(match: re.Match[str], count: int) -> str:
    """Replace only sizing facts while retaining responsibility prose."""
    text = match.group(0)
    text = re.sub(r"(?i)(\bcurrent\s+)\d+", rf"\g<1>{count}", text)
    text = re.sub(
        r"(?i)(remaining\s+headroom\s+)-?\d+",
        rf"\g<1>{DEFAULT_LIMIT - count}",
        text,
    )
    flag = str(count >= DEFAULT_LIMIT).lower()
    return re.sub(
        r"(?i)(at-or-over-limit\s*:\s*)(?:true|false)",
        rf"\g<1>{flag}",
        text,
    )


__all__ = [
    "FILE_BUDGET_REMEDIATION",
    "FileBudgetSizing",
    "parse_file_budget_sizing",
    "path_sizing_pattern",
    "replacement_for_current_size",
]
