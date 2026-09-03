from __future__ import annotations

import hashlib


def make_bundle(
    slug: str,
    *,
    version: str = "1.0.0",
    latest_version: str | None = None,
    dependencies: list[str] | None = None,
    render_values: dict[str, str] | None = None,
    files: dict[str, str],
) -> dict[str, object]:
    entries = [
        {
            "path": path,
            "content": content,
            "encoding": "utf-8",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "mode": 0o644,
        }
        for path, content in files.items()
    ]
    content_digest = hashlib.sha256(
        slug.encode("utf-8") + version.encode("utf-8")
    ).hexdigest()
    return {
        "bundle_schema": 2,
        "project_id": 9,
        "project_slug": "sample",
        "pack": slug,
        "name": slug.title(),
        "description": f"{slug} Pack.",
        "version": version,
        "latest_version": latest_version or version,
        "dependencies": dependencies or [],
        "prerequisites": [],
        "render_values": render_values or {},
        "files": entries,
        "content_digest": content_digest,
    }


def make_receipt_record(bundle: dict[str, object]) -> dict[str, object]:
    files = bundle["files"]
    assert isinstance(files, list)
    return {
        "version": bundle["version"],
        "content_digest": bundle["content_digest"],
        "render_values": bundle["render_values"],
        "prerequisites": bundle["prerequisites"],
        "files": {
            row["path"]: {
                "path": row["path"],
                "sha256": row["sha256"],
                "mode": row["mode"],
            }
            for row in files
        },
    }


__all__ = ["make_bundle", "make_receipt_record"]
