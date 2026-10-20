"""Complete labeled human values, with explicit empty states."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TextIO


def write_local(
    value: Any, stream: TextIO, *, writer=None, essential_writer=None
) -> None:
    """Bound a client-local receipt and save every oversized value."""
    import io
    from yoke_cli.transport.response_evidence import (
        save_response,
    )

    from yoke_cli.transport.output_limit import reply_exceeds_limit

    output = io.StringIO()
    if writer:
        writer(value, output)
    else:
        write_human(value, output)
    if not reply_exceeds_limit(output.getvalue()):
        stream.write(output.getvalue())
        return
    try:
        evidence = save_response(value, output.getvalue(), "")
    except OSError as exc:
        print(
            f"error (response_evidence_unavailable): {exc}. Restore writable temporary storage and inspect the operation's read before repeating a mutation.",
            file=stream,
        )
        raise SystemExit(1) from exc
    delivered = io.StringIO()
    print(f"Complete local result saved: {evidence}", file=delivered)
    print(
        "Open the file for every returned field. The operation already ran.",
        file=delivered,
    )
    if essential_writer:
        essential_writer(value, delivered)
    if reply_exceeds_limit(delivered.getvalue()):
        print(
            f"error (essential_output_limit_exceeded): immediate recovery exceeds the display limit. Read the complete local result at {evidence} before continuing.",
            file=stream,
        )
        raise SystemExit(1)
    stream.write(delivered.getvalue())


def label(key: Any) -> str:
    return str(key).replace("_", " ")


def scalar(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def write_human(
    value: Any, stream: TextIO, *, heading: str = "Result", indent: int = 0
) -> None:
    """Print every value; delivery size is handled by the response owner."""
    pad = " " * indent
    if isinstance(value, Mapping):
        if not value:
            print(f"{pad}{heading}: empty.", file=stream)
        for key, child in value.items():
            name = label(key)
            if isinstance(child, (Mapping, list, tuple)) and child:
                print(f"{pad}{name}:", file=stream)
                write_human(child, stream, heading=name, indent=indent + 2)
            else:
                write_human(child, stream, heading=name, indent=indent)
    elif isinstance(value, (list, tuple)):
        if not value:
            print(f"{pad}{heading}: no entries.", file=stream)
        elif all(
            isinstance(row, Mapping)
            and all(
                not isinstance(v, (Mapping, list, tuple))
                and not (isinstance(v, str) and any(char in v for char in "\n\r|"))
                for v in row.values()
            )
            for row in value
        ):
            columns = list(dict.fromkeys(key for row in value for key in row))
            if not columns:
                print(f"{pad}{heading}: {len(value)} empty records.", file=stream)
                return
            print(pad + " | ".join(label(key) for key in columns), file=stream)
            for row in value:
                print(
                    pad + " | ".join(scalar(row.get(key)) for key in columns),
                    file=stream,
                )
        else:
            for index, child in enumerate(value, 1):
                print(f"{pad}{heading} entry {index}:", file=stream)
                write_human(child, stream, indent=indent + 2)
    else:
        text = scalar(value)
        if "\n" in text:
            print(f"{pad}{heading}:", file=stream)
            print(text, file=stream)
        else:
            print(f"{pad}{heading}: {text}", file=stream)
