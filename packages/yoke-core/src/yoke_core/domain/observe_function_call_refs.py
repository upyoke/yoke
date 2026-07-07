"""Function-call envelope recognizer for observe attribution.

When a Bash command posts a Yoke function-call envelope to the local
dispatcher (``curl ... /v1/functions/call`` with either inline ``-d``
JSON or a ``--data-binary @<path>`` / ``-d @<path>`` file reference),
the wrapping ``HarnessToolCallCompleted`` row would otherwise miss
attribution because no ``YOK-N`` substring or ``--item`` flag appears
in the command. This helper extracts ``target.item_id`` from either
form so :func:`_resolve_explicit_refs` can populate ``rec.item_id``
and avoid the ``unattributed`` anomaly flag downstream.

The recognizer is best-effort: malformed JSON, oversized files, or
missing target attribution all return ``None`` silently — the caller
falls through to the existing attribution chain.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Match the dispatcher URL fragment; we only run the recognizer when
# a function-call POST is in flight.
_FUNCTIONS_CALL_RE = re.compile(r"/v1/functions/call\b")

# Inline ``-d`` / ``--data`` body containing ``item_id`` somewhere in
# the JSON payload. We extract just the numeric tail; presence of the
# function-call URL above guarantees this is a function-call envelope.
_INLINE_ITEM_ID_RE = re.compile(r'"item_id"\s*:\s*(\d+)')

# File reference shapes: ``--data-binary @PATH`` or ``-d @PATH`` or
# ``--data @PATH``. We capture the path up to the next quote / space.
_FILE_REF_RE = re.compile(
    r"(?:--data-binary|--data|-d)\s+@(\S+)"
)

# Best-effort cap on envelope file size; matches the existing
# run-attribution path's silent-failure posture.
_MAX_ENVELOPE_BYTES = 16 * 1024


def extract_function_call_item_id(command: str) -> Optional[str]:
    """Return the target.item_id from a function-call envelope in ``command``.

    Returns ``None`` when:
    - the command is not a function-call POST,
    - inline JSON has no ``item_id`` field,
    - the referenced envelope file is missing, unreadable, oversized,
      or does not parse as JSON with a numeric ``target.item_id``.
    """
    if not command or not _FUNCTIONS_CALL_RE.search(command):
        return None

    inline = _INLINE_ITEM_ID_RE.search(command)
    if inline:
        return inline.group(1)

    file_match = _FILE_REF_RE.search(command)
    if not file_match:
        return None

    raw_path = file_match.group(1).strip("'\"")
    try:
        envelope_path = Path(raw_path).expanduser()
        if not envelope_path.is_file():
            return None
        if envelope_path.stat().st_size > _MAX_ENVELOPE_BYTES:
            return None
        with envelope_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None
    target = payload.get("target")
    if not isinstance(target, dict):
        return None
    item_id = target.get("item_id")
    if isinstance(item_id, int):
        return str(item_id)
    if isinstance(item_id, str) and item_id.isdigit():
        return item_id
    return None
