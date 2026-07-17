#!/usr/bin/env python3
# Template authority: Yoke templates/webapp/ops/docker_image_cleanup.py.
"""Remove superseded images from selected Docker repositories safely.

The shared-host contract is deliberately narrower than ``image prune -a``:
only explicitly named repositories are considered.  Images referenced by any
container (running or stopped) are protected, as are explicit ``--keep``
references such as a not-yet-running tenant pin.  Removal is idempotent,
retries bounded transient failures, and exits nonzero when cleanup cannot be
completed so a deployment never reports a silently growing disk.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence

DEFAULT_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0

DockerResult = subprocess.CompletedProcess[str]
DockerRunner = Callable[[Sequence[str]], DockerResult]


class ImageCleanupError(RuntimeError):
    """Repository-scoped Docker image cleanup could not converge."""


def _docker(arguments: Sequence[str]) -> DockerResult:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        check=False,
        text=True,
    )


def _detail(result: DockerResult) -> str:
    return (result.stderr or result.stdout or f"rc={result.returncode}").strip()[-500:]


def _checked(runner: DockerRunner, arguments: Sequence[str]) -> DockerResult:
    result = runner(arguments)
    if result.returncode != 0:
        raise ImageCleanupError(
            f"docker {' '.join(arguments[:3])} failed: {_detail(result)}"
        )
    return result


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _image_id(runner: DockerRunner, reference: str) -> str | None:
    result = runner(["image", "inspect", "--format", "{{.Id}}", reference])
    if result.returncode != 0:
        if "no such image" in (result.stderr or result.stdout).lower():
            return None
        raise ImageCleanupError(
            f"could not inspect Docker image {reference}: {_detail(result)}"
        )
    values = _lines(result.stdout)
    if len(values) != 1:
        raise ImageCleanupError(
            f"Docker image inspect returned {len(values)} ids for {reference}"
        )
    return values[0]


def _container_image_ids(runner: DockerRunner) -> set[str]:
    containers = _lines(
        _checked(runner, ["container", "ls", "--all", "--quiet"]).stdout
    )
    if not containers:
        return set()
    inspected = _checked(
        runner,
        ["container", "inspect", "--format", "{{.Image}}", *containers],
    )
    return set(_lines(inspected.stdout))


def _protected_image_ids(
    runner: DockerRunner, keep_references: Iterable[str]
) -> set[str]:
    protected = _container_image_ids(runner)
    for reference in keep_references:
        image_id = _image_id(runner, reference)
        if image_id is None:
            raise ImageCleanupError(
                f"explicitly protected Docker image is absent: {reference}"
            )
        protected.add(image_id)
    return protected


def _repository_references(runner: DockerRunner, repository: str) -> list[str]:
    result = _checked(
        runner,
        [
            "image",
            "ls",
            "--all",
            "--no-trunc",
            "--format",
            "{{.Repository}}\t{{.Tag}}\t{{.ID}}",
            repository,
        ],
    )
    references: set[str] = set()
    for row in _lines(result.stdout):
        fields = row.split("\t")
        if len(fields) != 3:
            raise ImageCleanupError(
                f"unexpected Docker image listing row for {repository}: {row!r}"
            )
        listed_repository, tag, _image = fields
        if listed_repository == repository and tag != "<none>":
            references.add(f"{listed_repository}:{tag}")
    return sorted(references)


def _remove_reference(
    reference: str,
    *,
    runner: DockerRunner,
    keep_references: Sequence[str],
    attempts: int,
    pause: Callable[[float], None],
    emit: Callable[[str], None],
) -> bool:
    """Remove one tag, returning false when its image became protected."""
    last_failure = "unknown Docker failure"
    for attempt in range(1, attempts + 1):
        image_id = _image_id(runner, reference)
        if image_id is None:
            emit(f"image cleanup: already absent {reference}")
            return True
        if image_id in _protected_image_ids(runner, keep_references):
            emit(f"image cleanup: protected {reference} ({image_id})")
            return False

        result = runner(["image", "rm", reference])
        if result.returncode == 0:
            emit(f"image cleanup: removed {reference}")
            return True
        last_failure = _detail(result)

        # A container may have started between inventory and removal. Refresh
        # protection before retrying; Docker itself is the final race-safe
        # guard and refuses to remove container-owned images.
        refreshed_id = _image_id(runner, reference)
        if refreshed_id is None:
            emit(f"image cleanup: already absent {reference}")
            return True
        if refreshed_id in _protected_image_ids(runner, keep_references):
            emit(f"image cleanup: protected after concurrent use {reference}")
            return False
        if attempt < attempts:
            emit(
                f"image cleanup: remove attempt {attempt}/{attempts} failed "
                f"for {reference}; retrying"
            )
            pause(RETRY_DELAY_SECONDS)

    raise ImageCleanupError(
        f"could not remove {reference} after {attempts} attempts: {last_failure}"
    )


def cleanup_repositories(
    repositories: Sequence[str],
    *,
    keep_references: Sequence[str] = (),
    attempts: int = DEFAULT_ATTEMPTS,
    runner: DockerRunner = _docker,
    pause: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> int:
    """Remove unprotected tags and return the number successfully removed."""
    if attempts < 1:
        raise ImageCleanupError("attempts must be at least 1")
    repositories = tuple(
        dict.fromkeys(repository.strip() for repository in repositories)
    )
    if not repositories or any(not repository for repository in repositories):
        raise ImageCleanupError("at least one non-empty --repository is required")
    keep_references = tuple(
        dict.fromkeys(reference.strip() for reference in keep_references)
    )
    if any(not reference for reference in keep_references):
        raise ImageCleanupError("--keep references must be non-empty")

    # Validate every explicit keep before removing anything.  This makes a
    # missing next-tenant pin fail closed instead of pruning first and
    # discovering the protection typo afterward.
    _protected_image_ids(runner, keep_references)

    removed = 0
    for repository in repositories:
        for reference in _repository_references(runner, repository):
            if _remove_reference(
                reference,
                runner=runner,
                keep_references=keep_references,
                attempts=attempts,
                pause=pause,
                emit=emit,
            ):
                removed += 1
    emit(f"image cleanup: complete ({removed} superseded tags removed)")
    return removed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", required=True)
    parser.add_argument("--keep", action="append", default=[])
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cleanup_repositories(
            args.repository,
            keep_references=args.keep,
            attempts=args.attempts,
        )
    except ImageCleanupError as exc:
        print(f"image cleanup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
