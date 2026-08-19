"""Adapter for ``ouroboros.field_note.promote``.

Promotion turns a recorded field-note into a backlog item. It is reached
through the same direct-workflow registry as the Dash adapters and shares
their envelope shape, but it acts on an Ouroboros entry rather than on a
Dash, so it keeps its own module.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

FIELD_NOTE_PROMOTE_USAGE = (
    "yoke ouroboros field-note promote ENTRY --title TITLE "
    "[--instruction TEXT] [--project P] [--priority P] "
    "[--session-id S] [--json]"
)


def field_note_promote(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note promote",
        description=FIELD_NOTE_PROMOTE_USAGE,
    )
    parser.add_argument("entry", type=int)
    parser.add_argument("--title", required=True)
    parser.add_argument("--instruction")
    parser.add_argument("--project")
    parser.add_argument("--priority")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, FIELD_NOTE_PROMOTE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "entry_id": parsed.entry,
        "title": parsed.title,
    }
    for key in ("instruction", "project", "priority"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    return dispatch_and_emit(
        function_id="ouroboros.field_note.promote",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "FIELD_NOTE_PROMOTE_USAGE",
    "field_note_promote",
]
