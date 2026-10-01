"""Compact recovery text shared by automatic member close-out notices."""

from __future__ import annotations

import re

_REQUIREMENT_ID = re.compile(r"\brequirement\s+#?(\d+)\b", re.IGNORECASE)
_MISSING_LANDING_EVIDENCE = re.compile(
    r"\blanding evidence is missing ([a-z_]+(?:, [a-z_]+)*)\.", re.IGNORECASE
)


def close_out_failure_summary(public_ref: str, failure: str) -> str:
    """Name blocked requirements or evidence without embedding the raw refusal."""
    missing = _MISSING_LANDING_EVIDENCE.search(failure)
    if missing:
        return (
            f"Automatic close-out failed; missing landing evidence: {missing[1]}. "
            f"Record it with `yoke merge item {public_ref}` using `--result` and "
            f"`--verification`. Read the evidence: `yoke items get {public_ref} body`."
        )
    ids = list(dict.fromkeys(_REQUIREMENT_ID.findall(failure)))
    blocked = (
        "; unsatisfied requirements: " + ", ".join(f"#{value}" for value in ids)
        if ids
        else ""
    )
    return (
        f"Automatic close-out failed{blocked}. "
        f"Read the full gate: `yoke qa gate-summary --item {public_ref} --target implemented`."
    )
