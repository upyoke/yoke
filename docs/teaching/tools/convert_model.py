"""Convert array collections to record files; rerun after taking upstream arrays.

    yoke dev run -- python3 docs/teaching/tools/convert_model.py

Existing record files without an array source are untouched. When an array is
present, it is authoritative for its records. All destinations are checked
before any source is removed.
"""

from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .model import MODEL_ROOT, dump
else:
    from model import MODEL_ROOT, dump


def convert(root: Path) -> int:
    writes = {}
    sources = []

    def add(directory, record, position=None, **fields):
        record = dict(record, **fields)
        if position is not None:
            record["position"] = position
        record_id = record["id"]
        if (
            not record_id
            or record_id in {".", ".."}
            or "/" in record_id
            or "\\" in record_id
        ):
            raise ValueError(
                f"MODEL_RECORD_ID: {record_id!r}; use a single filename id"
            )
        target = directory / f"{record_id}.json"
        if target in writes:
            raise ValueError(f"DUPLICATE_ID: {target}; make record ids unique")
        writes[target] = dump(record)

    concepts = [
        (path, json.loads(path.read_text()))
        for path in sorted((root / "concepts").glob("*.json"))
    ]
    concepts.sort(key=lambda pair: pair[1].get("parent") is not None)
    positions = {}
    for path, data in concepts:
        if "nodes" not in data:
            continue
        sources.append(path)

        def walk(nodes, parent):
            for node in nodes:
                position = positions.get(parent, 0)
                positions[parent] = position + 1
                record = {k: v for k, v in node.items() if k != "children"}
                directory = root / "concepts" / (parent or "")
                add(directory, record, position, page=path.stem)
                full = f"{parent}/{node['id']}" if parent else node["id"]
                walk(node.get("children", []), full)

        walk(data["nodes"], data.get("parent"))

    for kind, owner_key, part in [
        ("surfaces", "surface", "teaching"),
        ("scenarios", "scenario", "lessons"),
    ]:
        for path in sorted((root / kind).glob("*.json")):
            data = json.loads(path.read_text())
            if owner_key not in data:
                continue
            sources.append(path)
            owner = data[owner_key]
            add(root / kind, owner)
            for position, record in enumerate(data.get(part, [])):
                add(root / kind / owner["id"], record, position)

    for path in sorted((root / "evidence").glob("*.json")):
        data = json.loads(path.read_text())
        if "records" not in data:
            continue
        sources.append(path)
        add(
            root / "evidence",
            {k: v for k, v in data.items() if k != "records"},
            id=path.stem,
        )
        for position, record in enumerate(data["records"]):
            add(root / "evidence" / path.stem, record, position)

    for kind in ["boundaries", "gaps"]:
        path = root / f"{kind}.json"
        if path.exists():
            sources.append(path)
            for position, record in enumerate(json.loads(path.read_text())["records"]):
                add(root / kind, record, position)

    for target, text in writes.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for source in sources:
        if source not in writes:
            source.unlink()
    return len(writes)


if __name__ == "__main__":
    try:
        print(f"teaching model: wrote {convert(MODEL_ROOT)} record files")
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(
            f"MODEL_CONVERSION: {error}; fix the source arrays and rerun"
        ) from None
