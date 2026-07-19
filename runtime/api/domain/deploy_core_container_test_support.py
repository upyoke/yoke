"""Project-owned source setup shared by core-container tests."""

from pathlib import Path
import shutil


def install_core_service_project_source(tmp_path: Path) -> Path:
    root = tmp_path / "service-project"
    pack_root = Path(__file__).resolve().parents[3] / "packs"
    for slug in ("container-runtime", "host-maintenance"):
        source = pack_root / slug / "versions/1.0.0/files"
        shutil.copytree(source, root, dirs_exist_ok=True)
    return root


__all__ = ["install_core_service_project_source"]
