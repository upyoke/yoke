"""Name report sessions with their existing person and machine identities."""

from dataclasses import fields, is_dataclass
import re
from typing import Any


def session_labels(conn: Any, reports, machine_names):
    ids = set()

    def collect(value):
        if is_dataclass(value):
            for field in fields(value):
                cell = getattr(value, field.name)
                if field.name.endswith("session_id") and cell:
                    ids.add(str(cell))
                else:
                    collect(cell)
        elif isinstance(value, (list, tuple)):
            for cell in value:
                collect(cell)

    collect(reports)
    if not ids:
        return ()
    from yoke_core.domain.session_display import session_display_names

    found = session_display_names(conn, sorted(ids))
    return tuple(
        (session, found.get(session, "session unavailable")) for session in sorted(ids)
    )


def label_text(text: str, labels) -> str:
    """Annotate session identities in prose, preserving executable commands."""
    names = dict(labels)
    if not names:
        return text
    pattern = re.compile(
        "|".join(re.escape(key) for key in sorted(names, key=len, reverse=True))
    )
    lines = []
    for line in text.splitlines():
        chunks = line.split("`")
        for index in range(0, len(chunks), 2):
            chunks[index] = pattern.sub(lambda match: names[match[0]], chunks[index])
        lines.append("`".join(chunks))
    return "\n".join(lines)


def label_rows(value, labels):
    """Add display labels beside session identity fields in JSON rows."""
    names = dict(labels)
    if isinstance(value, list):
        return [label_rows(row, names) for row in value]
    if not isinstance(value, dict):
        return value
    result = {key: label_rows(cell, names) for key, cell in value.items()}
    for key, cell in value.items():
        if key.endswith("session_id") and cell:
            result[key.removesuffix("_id") + "_label"] = names.get(
                str(cell), "person and machine unavailable"
            )
    return result
