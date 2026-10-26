"""Complete labeled human values, with explicit empty states."""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from typing import Any, TextIO


def write_local(value: Any, stream: TextIO, *, writer=None) -> None:
    """Print the complete client-local receipt."""
    if writer:
        writer(value, stream)
    else:
        write_human(value, stream)


def label(key: Any) -> str:
    return str(key).replace("_", " ")


def scalar(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _one_line_cell(value: Any) -> bool:
    return not isinstance(value, (Mapping, list, tuple)) and not any(
        char in scalar(value) for char in "\n\r|"
    )


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
            if (
                isinstance(child, (Mapping, list, tuple))
                and child
                and not (
                    isinstance(child, (list, tuple))
                    and all(_one_line_cell(v) for v in child)
                )
            ):
                print(f"{pad}{name}:", file=stream)
                write_human(child, stream, heading=name, indent=indent + 2)
            else:
                write_human(child, stream, heading=name, indent=indent)
    elif isinstance(value, (list, tuple)):
        if not value:
            print(f"{pad}{heading}: no entries.", file=stream)
        elif all(_one_line_cell(cell) for cell in value):
            print(f"{pad}{heading}: " + " | ".join(map(scalar, value)), file=stream)
        elif all(
            isinstance(row, (list, tuple))
            and row
            and all(_one_line_cell(cell) for cell in row)
            for row in value
        ):
            for row in value:
                print(pad + " | ".join(map(scalar, row)), file=stream)
        elif all(
            isinstance(row, Mapping) and all(_one_line_cell(v) for v in row.values())
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
            print(textwrap.indent(text, pad + "  "), file=stream)
        else:
            print(f"{pad}{heading}: {text}", file=stream)
