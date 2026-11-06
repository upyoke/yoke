"""Select diagnostic failures from GitHub job logs, excluding step setup."""

from __future__ import annotations

import re

from yoke_core.domain.github_actions_run_stall import STALLED_DISPATCH_TOKEN

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\S+Z\s+")
_GENERIC_ERRORS = (
    "process completed with exit code",
    "hosted train concluded failure",
    "deployment did not complete",
    "promotion did not complete",
)
_EXCEPTION = re.compile(r"^(?:[A-Za-z_]\w*\.)*[A-Z]\w*: \S")
_CODED_ERROR = re.compile(r"\berror \([^)]+\):")


def clean_lines(log: str) -> list[str]:
    lines = []
    in_env = False
    for raw in str(log or "").splitlines():
        line = _TIMESTAMP.sub("", _ANSI.sub("", raw))
        text = line.strip()
        if text == "env:":
            in_env = True
            continue
        if in_env:
            if text == "##[endgroup]":
                in_env = False
            elif line[:1].isspace() or not text:
                continue
            else:
                in_env = False
        lines.append(text)
    return lines


def error_score(text: str) -> tuple[int, int]:
    folded = text.casefold()
    if "stale pair:" in folded:
        return 95, len(text)
    if re.search(r"\b" + re.escape(STALLED_DISPATCH_TOKEN) + r"\b", folded):
        return 95, len(text)
    if "unauthorized: authentication required" in folded:
        return 100, len(text)
    if "must be the same commit" in folded:
        return 88, len(text)
    if "error response from daemon:" in folded:
        return 85, len(text)
    if "failed " in folded and " - " in text:
        return 80, len(text)
    if re.search(r"\bHTTP 5\d\d\b", text):
        return 75, len(text)
    if "error:" in folded or "##[error]" in folded or _CODED_ERROR.search(folded):
        return 70, len(text)
    return 0, len(text)


def terminal_candidate(log: str) -> tuple[tuple[int, int], str] | None:
    """Keep annotation priority when comparing failures across jobs."""
    lines = clean_lines(log)
    headers = [
        i
        for i, line in enumerate(lines)
        if line == "Traceback (most recent call last):"
    ]
    if headers:
        exceptions = [
            line for line in lines[headers[-1] + 1 :] if _EXCEPTION.match(line)
        ]
        if exceptions:
            text = exceptions[-1]
            return (120, len(text)), text
    candidates = []
    for line in lines:
        annotated = "##[error]" in line
        text = line.split("##[error]", 1)[-1].strip() if annotated else line
        folded = text.casefold()
        if not text or any(generic in folded for generic in _GENERIC_ERRORS):
            continue
        score = (110, len(text)) if annotated else error_score(text)
        if score[0]:
            candidates.append((score, text))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def terminal_error(log: str) -> str | None:
    """Select the most diagnostic non-relay error line from one job log."""
    candidate = terminal_candidate(log)
    return candidate[1] if candidate else None
