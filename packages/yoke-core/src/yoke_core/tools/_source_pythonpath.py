"""Source-tree PYTHONPATH helpers for Yoke test wrappers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

PACKAGE_SRC_RELS: tuple[str, ...] = (
    "packages/yoke-contracts/src",
    "packages/yoke-cli/src",
    "packages/yoke-core/src",
    "packages/yoke-harness/src",
)
SOURCE_RUN_RECIPE = "yoke dev run -- <command>"


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


def source_modules() -> tuple[str, ...]:
    """Import names owned by a source checkout, including repo-root runtime."""
    packages = tuple(
        Path(rel).parent.name.replace("-", "_") for rel in PACKAGE_SRC_RELS
    )
    return (*packages, "runtime")


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
        return (
            f"could not import {module} from source PYTHONPATH: {detail}. "
            f"Run direct source commands through `{SOURCE_RUN_RECIPE}`."
        )
    origin = Path(completed.stdout.strip()).resolve()
    try:
        origin.relative_to(root.resolve())
    except ValueError:
        return (
            f"{module} import origin is outside this checkout: {origin}. "
            f"Expected it under {root.resolve()}. Run direct source commands "
            f"through `{SOURCE_RUN_RECIPE}`."
        )
    return None


def import_origins(
    root: Path,
    *,
    env: Mapping[str, str],
    python: str = sys.executable,
) -> tuple[dict[str, str], str | None]:
    """Resolve every checkout-owned import in one clean child interpreter."""
    modules = source_modules()
    code = (
        "import importlib.util,json,pathlib; out={}; "
        f"mods={json.dumps(modules)}; "
        "[(lambda s,n: out.__setitem__(n, str(pathlib.Path(s.origin).resolve()) "
        "if s and s.origin else '<missing>'))(importlib.util.find_spec(n),n) "
        "for n in mods]; print(json.dumps(out,sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [python, "-c", code], cwd=str(root), env=dict(env),
            capture_output=True, text=True, timeout=10, check=False,
        )
    except Exception as exc:
        return {}, f"could not inspect source import origins: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return {}, f"could not inspect source import origins: {detail}"
    try:
        origins = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return {}, f"could not decode source import origins: {exc}"
    expected = root.resolve()
    for module in modules:
        raw = str(origins.get(module) or "<missing>")
        if raw == "<missing>":
            return origins, f"source import {module} is missing"
        try:
            Path(raw).resolve().relative_to(expected)
        except ValueError:
            return origins, (
                f"source import {module} resolved outside {expected}: {raw}"
            )
    return origins, None


__all__ = [
    "PACKAGE_SRC_RELS",
    "SOURCE_RUN_RECIPE",
    "import_origins",
    "import_origin_refusal",
    "repo_root",
    "source_entries",
    "source_modules",
    "with_source_pythonpath",
]
