"""Source-tree PYTHONPATH helpers for Yoke test wrappers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

PACKAGE_SRC_RELS: tuple[str, ...] = (
    "packages/yoke-contracts/src",
    "packages/yoke-cli/src",
    "packages/yoke-core/src",
    "packages/yoke-harness/src",
)


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return here


def source_entries(root: Path) -> list[str]:
    entries = [str((root / rel).resolve()) for rel in PACKAGE_SRC_RELS]
    entries.append(str(root.resolve()))
    return entries


def with_source_pythonpath(
    env: Mapping[str, str] | None,
    root: Path,
) -> dict[str, str]:
    out = dict(os.environ if env is None else env)
    existing = [
        value
        for value in out.get("PYTHONPATH", "").split(os.pathsep)
        if value
    ]
    ordered: list[str] = []
    for value in [*source_entries(root), *existing]:
        if value not in ordered:
            ordered.append(value)
    out["PYTHONPATH"] = os.pathsep.join(ordered)
    return out


def import_origin_refusal(
    root: Path,
    *,
    env: Mapping[str, str],
    module: str = "yoke_core",
    python: str = sys.executable,
) -> str | None:
    code = (
        "import pathlib, " + module + "; "
        "print(pathlib.Path(" + module + ".__file__).resolve())"
    )
    try:
        completed = subprocess.run(
            [python, "-c", code],
            cwd=str(root),
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return f"could not verify {module} import origin: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return f"could not import {module} from source PYTHONPATH: {detail}"
    origin = Path(completed.stdout.strip()).resolve()
    try:
        origin.relative_to(root.resolve())
    except ValueError:
        return (
            f"{module} import origin is outside this checkout: {origin}. "
            f"Expected it under {root.resolve()}."
        )
    return None


__all__ = [
    "PACKAGE_SRC_RELS",
    "import_origin_refusal",
    "repo_root",
    "source_entries",
    "with_source_pythonpath",
]
