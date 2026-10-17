"""Recovery text shared by automatic member close-out notices.

The notice keeps the refusal's own reason: its headline and each record line
the gate named (``  - run #49091: requirement 46094 latest execution: ...``),
so the owner reads what blocked close-out without a second lookup. Each line
and the line count are bounded so the notice fits every harness inline cap;
anything cut is named and the full gate read is always included.
"""

from __future__ import annotations

import re

_MISSING_LANDING_EVIDENCE = re.compile(
    r"\blanding evidence is missing ([a-z_]+(?:, [a-z_]+)*)\.", re.IGNORECASE
)
_RECORD_LINE = re.compile(r"^\s*- (.+)$")
_LINE_CHARS = 280
_MAX_RECORDS = 6


def _bounded(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _LINE_CHARS else text[: _LINE_CHARS - 1] + "…"


def close_out_failure_summary(public_ref: str, failure: str) -> str:
    """Name the refusal and its blocking records, then the full gate read."""
    missing = _MISSING_LANDING_EVIDENCE.search(failure)
    if missing:
        return (
            f"Automatic close-out failed; missing landing evidence: {missing[1]}. "
            f"Record it with `yoke merge item {public_ref}` using `--result` and "
            f"`--verification`. Read the evidence: `yoke items get {public_ref} body`."
        )
    lines = [line for line in str(failure).splitlines() if line.strip()]
    headline = next((line for line in lines if not _RECORD_LINE.match(line)), "refused")
    records = [m[1] for line in lines if (m := _RECORD_LINE.match(line))]
    parts = [
        "Automatic close-out failed: " + _bounded(headline.removeprefix("Error: "))
    ]
    parts.extend(f"  - {_bounded(record)}" for record in records[:_MAX_RECORDS])
    if len(records) > _MAX_RECORDS:
        parts.append(f"  - and {len(records) - _MAX_RECORDS} more record(s)")
    parts.append(
        "Read the full gate: "
        f"`yoke qa gate-summary --item {public_ref} --target implemented`."
    )
    return "\n".join(parts)
