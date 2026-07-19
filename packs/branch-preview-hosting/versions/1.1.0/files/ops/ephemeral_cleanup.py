#!/usr/bin/env python3
"""Remove preview resources older than the configured time-to-live.

Scheduling is project-owned. Install this with cron, systemd, or another host
scheduler after reviewing the paths and resource prefix below.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


PREVIEW_NAMESPACE = "{{preview_namespace}}"
PREVIEW_ROOT = Path.home() / PREVIEW_NAMESPACE
TTL_HOURS = int("{{preview_ttl_hours}}")
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{timestamp} [preview-cleanup] {message}", flush=True)


def run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return completed.returncode, completed.stdout


def compose_project_to_slug(name: str) -> str | None:
    prefix = f"{PREVIEW_NAMESPACE}-"
    slug = name.removeprefix(prefix) if name.startswith(prefix) else ""
    return slug if _SLUG.fullmatch(slug) else None


def image_repository_to_slug(repository: str) -> str | None:
    prefix = f"{PREVIEW_NAMESPACE}-"
    remainder = repository.removeprefix(prefix) if repository.startswith(prefix) else ""
    slug, separator, _service = remainder.rpartition("-")
    return slug if separator and _SLUG.fullmatch(slug) else None


def volume_name_to_slug(name: str) -> str | None:
    prefix = f"{PREVIEW_NAMESPACE}-"
    remainder = name.removeprefix(prefix) if name.startswith(prefix) else ""
    slug = remainder.partition("_")[0]
    return slug if "_" in remainder and _SLUG.fullmatch(slug) else None


def compose_slugs() -> set[str]:
    status, output = run(["docker", "compose", "ls", "--format", "json"])
    if status != 0 or not output.strip():
        return set()
    try:
        rows = json.loads(output)
    except json.JSONDecodeError:
        return set()
    if not isinstance(rows, list):
        return set()
    return {
        slug
        for row in rows
        if isinstance(row, dict)
        for slug in [compose_project_to_slug(str(row.get("Name", "")))]
        if slug
    }


def images() -> list[tuple[str, str, str]]:
    status, output = run(["docker", "images", "--format", "{{.Repository}}\t{{.Tag}}"])
    if status != 0:
        return []
    found = []
    for line in output.splitlines():
        repository, separator, tag = line.partition("\t")
        slug = image_repository_to_slug(repository)
        if separator and slug:
            found.append((slug, repository, tag))
    return found


def volumes() -> list[tuple[str, str]]:
    status, output = run(["docker", "volume", "ls", "--format", "{{.Name}}"])
    if status != 0:
        return []
    return [
        (slug, name)
        for name in output.splitlines()
        for slug in [volume_name_to_slug(name)]
        if slug
    ]


def preview_directories() -> dict[str, Path]:
    if not PREVIEW_ROOT.is_dir():
        return {}
    return {
        child.name: child
        for child in PREVIEW_ROOT.iterdir()
        if child.is_dir() and _SLUG.fullmatch(child.name)
    }


def main() -> int:
    if shutil.which("docker") is None:
        log("ERROR: docker not found in PATH")
        return 0

    directories = preview_directories()
    image_rows = images()
    volume_rows = volumes()
    slugs = (
        set(directories)
        | compose_slugs()
        | {row[0] for row in image_rows}
        | {row[0] for row in volume_rows}
    )
    if not slugs:
        log("No preview resources found.")
        return 0

    now = time.time()
    cutoff = now - TTL_HOURS * 3600
    cleaned = 0
    kept = 0
    errors = 0
    for slug in sorted(slugs):
        directory = directories.get(slug)
        age: str | int = "orphaned"
        stale = directory is None
        if directory is not None:
            try:
                modified = directory.stat().st_mtime
                age = max(0, int((now - modified) / 3600))
                stale = modified < cutoff
            except OSError:
                age = "unknown"
                stale = True
        if not stale:
            log(f"Keeping {slug} (age={age}h, ttl={TTL_HOURS}h)")
            kept += 1
            continue

        log(f"Removing {slug} (age={age}, ttl={TTL_HOURS}h)")
        run(
            [
                "docker",
                "compose",
                "-p",
                f"{PREVIEW_NAMESPACE}-{slug}",
                "down",
                "--volumes",
                "--remove-orphans",
            ],
            cwd=directory,
        )
        for resource_slug, repository, tag in image_rows:
            if resource_slug != slug:
                continue
            reference = (
                repository if not tag or tag == "<none>" else f"{repository}:{tag}"
            )
            run(["docker", "rmi", reference])
        for resource_slug, name in volume_rows:
            if resource_slug == slug:
                run(["docker", "volume", "rm", name])
        if directory is not None:
            try:
                shutil.rmtree(directory)
            except OSError:
                log(f"ERROR: could not remove {directory}")
                errors += 1
                continue
        cleaned += 1

    log(f"Finished: removed={cleaned} kept={kept} errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
