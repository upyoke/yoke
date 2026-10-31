"""Compare shipped third-party distributions with the source lock."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from yoke_core.tools import package_index
from yoke_core.tools.release_artifacts import ReleaseBuildError
from yoke_core.tools.server_image_metadata import version_mismatches


def assert_locked_wheelhouse(repo_root: Path, wheelhouse: Path) -> None:
    """Apply the lock check to every dependency wheel in the offline closure."""
    records = package_index.read_wheel_records(wheelhouse)
    mismatches = version_mismatches(
        repo_root / "uv.lock", ((record.name, record.version) for record in records)
    )
    if mismatches:
        raise ReleaseBuildError(
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
