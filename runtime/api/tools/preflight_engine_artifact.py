"""Bind fleet preflight imports to one exact engine wheel."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
from typing import Dict


class EngineArtifactError(ValueError):
    """An explicitly selected engine artifact cannot be used faithfully."""


@dataclass(frozen=True)
class EngineArtifact:
    kind: str
    name: str
    sha256: str
    schema_origin: str

    def evidence(self) -> Dict[str, str]:
        values = {
            "kind": self.kind,
            "name": self.name,
            "schema_origin": self.schema_origin,
        }
        if self.sha256:
            values["sha256"] = self.sha256
        return values

    def display(self) -> str:
        digest = f" sha256:{self.sha256}" if self.sha256 else ""
        return f"{self.kind} {self.name}{digest} schema={self.schema_origin}"


def activate_engine_artifact(raw_wheel: str) -> EngineArtifact:
    """Bind yoke_core to a selected wheel, or describe the ambient engine."""
    if not raw_wheel:
        schema = importlib.import_module("yoke_core.domain.schema_init")
        return EngineArtifact(
            kind="ambient",
            name="import-path",
            sha256="",
            schema_origin=str(getattr(schema, "__file__", "unknown")),
        )

    wheel = Path(raw_wheel).expanduser().resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise EngineArtifactError(f"engine wheel is not a readable .whl file: {wheel}")
    loaded = sorted(
        name
        for name in sys.modules
        if name == "yoke_core" or name.startswith("yoke_core.")
    )
    if loaded:
        raise EngineArtifactError(
            "cannot select an engine wheel after yoke_core loaded: "
            + ", ".join(loaded[:5])
        )
    import_root = _extract_wheel(wheel)
    sys.path.insert(0, str(import_root))
    importlib.invalidate_caches()
    try:
        schema = importlib.import_module("yoke_core.domain.schema_init")
    except (ImportError, OSError) as exc:
        raise EngineArtifactError(
            f"selected engine wheel cannot import schema_init: {exc}"
        ) from exc
    origin = Path(str(getattr(schema, "__file__", ""))).resolve()
    try:
        schema_member = origin.relative_to(import_root).as_posix()
    except ValueError as exc:
        raise EngineArtifactError(
            f"selected engine resolved outside its wheel: {origin}"
        ) from exc
    return EngineArtifact(
        kind="wheel",
        name=wheel.name,
        sha256=_file_sha256(wheel),
        schema_origin=schema_member,
    )


def _extract_wheel(wheel: Path) -> Path:
    root = Path(tempfile.mkdtemp(prefix="yoke-preflight-engine-")).resolve()
    try:
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                target = (root / member.filename).resolve()
                if target != root and root not in target.parents:
                    raise EngineArtifactError(
                        "engine wheel member escapes extraction root: "
                        f"{member.filename}"
                    )
            archive.extractall(root)
    except EngineArtifactError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise EngineArtifactError(f"engine wheel cannot be extracted: {exc}") from exc
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    return root


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["EngineArtifact", "EngineArtifactError", "activate_engine_artifact"]
