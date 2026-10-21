"""Portable, exact-checkout product wheels shared by CI jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from packaging.utils import parse_wheel_filename

from yoke_core.tools import build_release, package_index

MANIFEST = "product-wheels.json"


def _identity(repo_root: Path) -> dict[str, str]:
    def revision(ref: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", ref], text=True, timeout=30
        ).strip()

    return {"commit": revision("HEAD"), "tree": revision("HEAD^{tree}")}


def _wheel_hashes(directory: Path) -> dict[str, str]:
    files = sorted(directory.glob("*.whl"))
    names = []
    for wheel in files:
        name, _version, _build, tags = parse_wheel_filename(wheel.name)
        if {str(tag) for tag in tags} != {"py3-none-any"}:
            raise ValueError("only py3-none-any product wheels can be shared")
        names.append(str(name))
    if sorted(names) != sorted(package_index.PRODUCT_PACKAGE_NAMES):
        raise ValueError("artifact must contain exactly one wheel per product package")
    package_index.validate_records(package_index.read_wheel_records(directory))
    return {wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest() for wheel in files}


def build_artifact(repo_root: Path, directory: Path) -> None:
    identity = _identity(repo_root)
    build_release.build_product_wheels(repo_root=repo_root, wheelhouse=directory)
    payload = {"schema": 1, **identity, "wheels": _wheel_hashes(directory)}
    (directory / MANIFEST).write_text(json.dumps(payload, sort_keys=True) + "\n")


def consume_artifact(repo_root: Path, directory: Path, wheelhouse: Path) -> None:
    """Validate immutable products, then build this interpreter's closure."""
    try:
        payload = json.loads((directory / MANIFEST).read_text())
        expected = {"schema": 1, **_identity(repo_root), "wheels": _wheel_hashes(directory)}
        if payload != expected:
            raise ValueError("manifest identity or wheel hashes differ from this checkout")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        raise ValueError(
            "ci_product_wheels_invalid: " + str(exc)
            + "; rebuild and download the product-wheels artifact from this exact CI run"
        ) from exc
    wheelhouse.mkdir(parents=True, exist_ok=True)
    if any(wheelhouse.iterdir()):
        raise ValueError(
            "ci_product_wheelhouse_not_empty: use a fresh per-job wheelhouse before retrying"
        )
    for filename in expected["wheels"]:
        shutil.copyfile(directory / filename, wheelhouse / filename)
    try:
        build_release.complete_product_wheelhouse(repo_root=repo_root, wheelhouse=wheelhouse)
    except (OSError, ValueError, build_release.ReleaseBuildError, subprocess.SubprocessError) as exc:
        raise ValueError(
            f"ci_product_wheel_closure_failed: {exc}; repair dependency resolution or "
            "the installed-core proof, then rerun with a fresh per-job wheelhouse"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_artifact(args.repo_root.resolve(), args.output.resolve())
    except (OSError, ValueError, build_release.ReleaseBuildError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"ci_product_wheels_build_failed: {exc}; fix the build and rerun CI\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
