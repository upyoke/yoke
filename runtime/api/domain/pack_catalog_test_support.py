from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain import pack_catalog


def write_pack(
    root: Path,
    *,
    slug: str = "sample",
    files: dict[str, str | bytes],
    documentation: str = "docs/packs/sample/README.md",
    copy_files: set[str] | None = None,
) -> Path:
    pack = root / "packs" / slug
    source = pack / "versions" / "1.0.0" / "files"
    source.mkdir(parents=True)
    for rel, content in files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    copied = copy_files or set()
    placeholders: set[str] = set()
    file_records: list[dict[str, str]] = []
    for rel, content in sorted(files.items()):
        render = "copy" if rel in copied else "install"
        target = (
            rel if render == "copy" else (rel[:-5] if rel.endswith(".tmpl") else rel)
        )
        file_records.append(
            {"source": rel, "target": target, "mode": "0644", "render": render}
        )
        if render == "install" and isinstance(content, str):
            placeholders.update(pack_catalog._PLACEHOLDER.findall(target))
            placeholders.update(pack_catalog._PLACEHOLDER.findall(content))
    (pack / "pack.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "slug": slug,
                "name": slug.title(),
                "description": f"{slug.title()} Pack.",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "source": "versions/1.0.0/files",
                        "documentation": documentation,
                        "dependencies": [],
                        "prerequisites": [],
                        "settings_schema": {
                            "type": "object",
                            "properties": {
                                key: {
                                    "type": "string",
                                    "description": f"Value for {key}.",
                                }
                                for key in sorted(placeholders)
                            },
                            "required": sorted(placeholders),
                            "additionalProperties": False,
                        },
                        "files": file_records,
                        "verification": [
                            {"name": "source-check", "command": "git diff --check"}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return source


__all__ = ["write_pack"]
