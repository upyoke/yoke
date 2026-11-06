"""Render complete architecture drafts without repeating directory prefixes."""

from __future__ import annotations

from itertools import groupby
from typing import Any, TextIO


def _paths(entries: list[dict], value_key: str, stream: TextIO) -> None:
    # Keep declaration order, including an area's final catch-all after its
    # child directories: first-match precedence is part of the map.
    for parent, group in groupby(entries, key=lambda entry: entry["glob"].rpartition("/")[0]):
        patterns = [
            f"{entry['glob'].rpartition('/')[2]} [{entry[value_key]}]"
            for entry in group
        ]
        prefix = f"{parent}/: " if parent else "./: "
        print(prefix + "; ".join(patterns), file=stream)
    if not entries:
        print("No entries.", file=stream)


def write_architecture_draft(result: dict[str, Any], stream: TextIO) -> None:
    if "project_id" in result:
        print(f"Project: {result['project_id']}", file=stream)
    payload = result["payload"]
    print("## Layers", file=stream)
    for layer in payload["layers"]:
        depends = ", ".join(layer["may_depend_on"]) or "none"
        forbidden = ", ".join(layer["forbidden_edges"]) or "none"
        print(f"{layer['id']}: may depend on {depends}; forbidden edges {forbidden}", file=stream)
    for domain in payload["domains"]:
        print(f"## Domain {domain['id']}", file=stream)
        _paths(domain["path_roots"], "layer", stream)
    print("## Exemptions", file=stream)
    _paths(payload.get("exemptions", []), "family", stream)
    print("## Notes", file=stream)
    for note in result["notes"]:
        print(note, file=stream)
