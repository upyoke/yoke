"""Make a release-time fleet rehearsal run the code the release ships.

Coverage is recorded by history entry name and schema-shape digest, so a
rehearsal that ran other code than the release commit's would record
coverage for entries it never executed. A ``named_databases`` fleet therefore
converges from an exact checkout of the release commit, made beside the
project repository and removed afterwards. An ``engine_tenants`` fleet
converges with the dispatching engine's own source, so that source must be
proven identical to the release commit's — every history entry byte for byte
and the schema-shape digest — before it may rehearse on the release's behalf.
"""

from __future__ import annotations

from yoke_core.domain.deployment_run_recovery_command import deploy_command
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


class ReleaseSourceError(RuntimeError):
    """The release commit's source could not be made available to rehearse."""


@contextmanager
def release_checkout(repository: str, release_sha: str) -> Iterator[Path]:
    """An exact, disposable checkout of *release_sha* from *repository*."""
    with tempfile.TemporaryDirectory(prefix="yoke-release-rehearsal-") as work:
        checkout = Path(work) / "checkout"
        for argv in (
            [
                "git",
                "clone",
                "--quiet",
                "--shared",
                "--no-checkout",
                str(Path(repository).expanduser()),
                str(checkout),
            ],
            [
                "git",
                "-C",
                str(checkout),
                "checkout",
                "--quiet",
                "--detach",
                release_sha,
            ],
        ):
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=300, check=False
            )
            if result.returncode != 0:
                raise ReleaseSourceError(
                    f"could not check out release commit {release_sha} from "
                    f"{repository}: {(result.stderr or result.stdout).strip()}. "
                    "Fetch the commit into that repository and re-run the release."
                )
        yield checkout


def ensure_commit(repository: str, sha: str, run_id: str) -> str:
    """Fetch *sha* into *repository* when it is missing; why not, or ``""``."""
    root = str(Path(repository).expanduser())

    def git(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", root, *argv],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    if git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        return ""
    fetched = git("fetch", "--quiet", "origin", sha)
    if fetched.returncode == 0:
        return ""
    return (
        f"commit {sha} is not in {root} and fetching it from origin failed: "
        f"{(fetched.stderr or fetched.stdout).strip()}. Run `git -C {root} "
        f"fetch origin {sha}`, then re-drive the run with `{deploy_command(run_id)}`"
    )


def engine_source_mismatch(
    repository: str,
    release_sha: str,
    modules_dir: str,
    history: Sequence[str],
    release_schema_digest: str,
) -> str:
    """Why the dispatching engine is not the release commit, or ``""``."""
    from yoke_core.domain import migrations as history_package
    from yoke_core.domain.migration_history import history_dir, ordered_entries
    from yoke_core.domain.schema_shape_source import digest_schema_shape

    running = {
        entry.name: entry.content_sha256
        for entry in ordered_entries(history_dir(history_package))
    }
    remedy = (
        "Run the release driver from the release commit's own source so the "
        "rehearsal executes exactly what the release ships."
    )
    if tuple(running) != tuple(history):
        return (
            f"the dispatching engine's migration history differs from release "
            f"commit {release_sha}'s; {remedy}"
        )
    from yoke_core.domain.migration_history_integration import _target_history

    released = {
        entry.name: entry.content_sha256
        for entry in _target_history(Path(repository), release_sha, modules_dir)
    }
    for name in history:
        if released.get(name) != running[name]:
            return (
                f"history entry {name} in the dispatching engine differs from "
                f"release commit {release_sha}'s; {remedy}"
            )
    if digest_schema_shape() != release_schema_digest:
        return (
            f"the dispatching engine's schema shape differs from release commit "
            f"{release_sha}'s; {remedy}"
        )
    return ""


__all__ = [
    "ReleaseSourceError",
    "engine_source_mismatch",
    "ensure_commit",
    "release_checkout",
]
