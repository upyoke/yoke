"""Qualify the rendered scaffold with its own declared Python dependencies."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from yoke_core.domain import install_bundle_tree_sync, pack_catalog

ROOT = Path(__file__).resolve().parents[3]


def test_scaffold_clock_kernel_and_permanent_history_bytes():
    pack = ROOT / "packs/webapp-scaffold"
    release = pack_catalog.load_pack_descriptor("webapp-scaffold")
    source = pack / release["versions"][release["latest_version"]]["source"]
    assert (source / "app/utils/timestamps.py").read_bytes() == (
        ROOT / "packages/yoke-contracts/src/yoke_contracts/timestamps.py"
    ).read_bytes()
    previous = pack / "versions/1.1.3/files"
    assert (source / "app/db/migrations/0001_initial_schema.py").read_bytes() == (
        previous / "app/db/migrations/0001_initial_schema.py"
    ).read_bytes()
    assert (source / "app/tests/fixtures/auth_legacy_schema.sql").read_bytes() == (
        previous / "app/db/schema.sql"
    ).read_bytes()
    assert (source / "app/db/migrations/0002_canonical_instants.py").read_bytes() == (
        ROOT
        / install_bundle_tree_sync.PACKAGED_TREE_REL
        / "packs/webapp-scaffold"
        / "versions/1.1.4/files/app/db/migrations/0002_canonical_instants.py"
    ).read_bytes()


def test_rendered_scaffold_backend_qualifies_with_declared_dependencies(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
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
    for entry in bundle["files"]:
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry["content"], encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "PYTHONPATH" and not key.startswith("YOKE_")
    }
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with-requirements",
            "app/requirements.txt",
            "python3",
            "-m",
            "pytest",
            "app/tests",
            "--confcutdir",
            "app/tests",
            "-q",
            "-o",
            "addopts=",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    (tmp_path / "scaffold-backend-qualification.txt").write_text(
        result.stdout, encoding="utf-8"
    )
    assert result.returncode == 0, result.stdout
    assert "skipped" not in result.stdout, result.stdout
