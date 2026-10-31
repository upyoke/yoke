"""Compare shipped third-party distributions with the source lock."""

from __future__ import annotations

import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Mapping

from packaging.utils import canonicalize_name
from packaging.version import Version

from yoke_core.tools import package_index


def version_mismatches(lock_path: Path, installed: Mapping[str, str]) -> list[str]:
    """Report every unlocked or changed distribution, excluding workspace products."""
    lock = tomllib.loads(lock_path.read_text())
    products = {canonicalize_name(name) for name in lock["manifest"]["members"]}
    versions: dict[str, set[Version]] = {}
    for package in lock["package"]:
        if "registry" in package["source"]:
            versions.setdefault(canonicalize_name(package["name"]), set()).add(
                Version(package["version"])
            )
    mismatches = []
    for name, actual in sorted(installed.items()):
        name = canonicalize_name(name)
        if name in products:
            continue
        expected = versions.get(name, set())
        if Version(actual) not in expected:
            wanted = ",".join(str(value) for value in sorted(expected)) or "absent from uv.lock"
            mismatches.append(f"{name}: installed={actual} locked={wanted}")
    return mismatches


def assert_locked_wheelhouse(repo_root: Path, wheelhouse: Path) -> None:
    """Apply the lock check to every dependency wheel in the offline closure."""
    records = package_index.read_wheel_records(wheelhouse)
    mismatches = version_mismatches(
        repo_root / "uv.lock", {record.name: record.version for record in records}
    )
    if mismatches:
        raise ValueError(
            "wheelhouse_lock_mismatch:\n" + "\n".join(mismatches)
            + "\nRebuild the wheelhouse from uv.lock before publishing."
        )


@contextmanager
def exported_constraints(repo_root: Path, uv: str, run: Callable) -> Iterator[Path]:
    """Let uv own freshness checking and marker-preserving lock export."""
    with tempfile.TemporaryDirectory(prefix="yoke-lock-constraints-") as work:
        constraints = Path(work) / "constraints.txt"
        run(
            [uv, "export", "--locked", "--no-default-groups", "--group", "release",
             "--no-emit-workspace", "--no-hashes", "--output-file", str(constraints)],
            cwd=repo_root,
        )
        yield constraints
