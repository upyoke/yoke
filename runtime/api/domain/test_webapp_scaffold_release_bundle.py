"""Released Pack snapshot carries the canonical webapp migration identity."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import install_bundle_tree_sync, pack_catalog


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_ROOT = REPO_ROOT / install_bundle_tree_sync.PACKAGED_TREE_REL


def test_packaged_webapp_bundle_exposes_content_identity_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = REPO_ROOT / "packs/webapp-scaffold"
    packaged = PACKAGED_ROOT / "packs/webapp-scaffold"
    assert (packaged / "pack.json").read_bytes() == (
        canonical / "pack.json"
    ).read_bytes()
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: PACKAGED_ROOT)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )

    descriptor = pack_catalog.load_pack_descriptor("webapp-scaffold")
    bundle = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="webapp-scaffold",
        render_values={
            "api_port": "8000",
            "project_description": "Sample application.",
            "project_display_name": "Sample App",
            "project_name": "sample",
            "project_slug": "sample",
            "web_port": "3000",
        },
    )

    assert descriptor["latest_version"] == "1.1.2"
    assert bundle["version"] == "1.1.2"
    release = descriptor["versions"]["1.1.2"]
    declared_sources = {row["source"] for row in release["files"]}
    release_root = canonical / release["source"]
    actual_sources = {
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert declared_sources == actual_sources
    paths = {row["path"] for row in bundle["files"]}
    assert "app/db/migrations/adoption_manifest.py" in paths
    assert "app/db/migrations/content_identity.py" in paths
    assert "app/db/migrations/receipt_guards.py" in paths
    assert "app/tests/test_migration_adoption_atomicity.py" in paths
    assert "app/tests/test_migration_adoption_receipts.py" in paths
    assert "app/tests/test_migration_content_identity.py" in paths
    settings = json.loads(
        (packaged / "versions/1.1.2/settings-reference.json").read_text(
            encoding="utf-8"
        )
    )
    ledger = settings["migration_model_defaults"]["models"]["primary"]["runner"][
        "config"
    ]["ledger"]
    assert ledger["digest_column"] == "content_sha256"
