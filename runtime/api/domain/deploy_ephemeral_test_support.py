"""Project-owned Pack source setup for ephemeral deploy tests."""

import json
from pathlib import Path
import shutil


def install_ephemeral_project_source(tmp_path: Path) -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "ephemeral-project"
    for pack_slug in ("ephemeral-environments", "branch-preview-hosting"):
        pack_root = repository_root / "packs" / pack_slug
        descriptor = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
        version = descriptor["versions"][descriptor["latest_version"]]
        source_root = pack_root / version["source"]
        for record in version["files"]:
            source = source_root / record["source"]
            target = project_root / record["target"].replace("{{project_name}}", "yoke")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    core_template = repository_root / (
        "ops/core-service/docker-compose.ephemeral.yml.tmpl"
    )
    core_target = project_root / ("ops/core-service/docker-compose.ephemeral.yml.tmpl")
    core_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(core_template, core_target)
    return project_root


__all__ = ["install_ephemeral_project_source"]
