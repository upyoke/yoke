"""Webapp scaffold documentation distinguishes app-local SQLite."""

import json
from pathlib import Path


def test_webapp_pack_docs_mark_sqlite_as_app_local() -> None:
    root = Path(__file__).resolve().parents[3]
    reference = json.loads(
        (
            root / "packs/webapp-scaffold/versions/1.0.0/settings-reference.json"
        ).read_text()
    )
    rels = (
        "packs/webapp-scaffold/versions/1.0.0/files/docs/packs/webapp-scaffold/README.md",
        "packs/webapp-scaffold/versions/1.0.0/files/AGENTS.md",
        "packs/webapp-scaffold/versions/1.0.0/files/ROADMAP.md",
        ".yoke/docs/reference/db-reference/migration-model-capabilities.md",
    )
    texts = [(root / rel).read_text() for rel in rels]
    assert "app-local SQLite" in reference["description"]
    assert all("app-local" in text for text in texts)
    assert all("Postgres control plane" in text for text in texts[1:])
    assert all("data/yoke.db" in text for text in (texts[1], texts[3]))
