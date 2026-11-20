"""Read JSON-valued CLI arguments from a literal, file or stdin."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

JSON_INPUT_HELP = "Pass inline JSON, @FILE for a UTF-8 file, or - for stdin."
_WINDOWS = sys.platform == "win32"


def load_json_input(value: str, flag: str, *, as_text: bool = False) -> Any:
    """Load JSON, optionally retaining its original text for string payloads."""
    from_file = value.startswith("@")
    from_stdin = value == "-"
    try:
        if from_file:
            document = Path(value[1:]).read_text(encoding="utf-8-sig")
        elif from_stdin:
            document = sys.stdin.read().removeprefix("\ufeff")
        else:
            document = value
    except (OSError, ValueError) as exc:
        raise ValueError(
            compose_refusal(
                f"{flag}: cannot read JSON input ({exc})",
                recovery=f"Pass a readable UTF-8 file with `{flag} @FILE` "
                f"or pipe JSON into `{flag} -`",
            )
        ) from None

    try:
        parsed = json.loads(document)
    except json.JSONDecodeError as exc:
        if from_file or from_stdin:
            source = "the file" if from_file else "stdin"
            raise ValueError(
                compose_refusal(
                    f"{flag}: {source} contains invalid JSON ({exc})",
                    recovery=f"Correct the JSON in {source} and retry",
                )
            ) from None
        if not _WINDOWS:
            raise
        raise ValueError(
            compose_refusal(
                f"{flag} is not valid JSON ({exc}). "
                "PowerShell drops inner quotes when calling yoke.cmd",
                recovery="Save the JSON to a file with "
                "`$json | Out-File -Encoding utf8 d.json` "
                f"and pass `{flag} '@d.json'` ({flag} @FILE)",
            )
        ) from None
    return document if as_text else parsed
