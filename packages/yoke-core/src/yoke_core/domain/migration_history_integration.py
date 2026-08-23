"""Prove that a lane's numbered migration history extends its target."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from yoke_core.domain.migration_content_identity import raw_content_sha256
from yoke_core.domain.migration_history import (
    ENTRY_NAME_PATTERN,
    HistoryError,
    ordinal_entries,
)


RELEASED_DIGESTS_NAME = "released_history_digests.json"


@dataclass(frozen=True)
class HistoryIdentity:
    sequence: int
    name: str
    content_sha256: str


def migration_ordinal(identifier: str) -> int | None:
    """Return an entry's numeric ordinal, or ``None`` for slug-only modules."""
    match = ENTRY_NAME_PATTERN.fullmatch(str(identifier))
    return int(match.group(1)) if match is not None else None


def _numbered_identifiers(identifiers: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        str(identifier)
        for identifier in identifiers
        if migration_ordinal(str(identifier)) is not None
    )


def _git(
    repo: Path,
    *args: str,
    required: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HistoryError(
            f"migration history integration check could not run git: {exc}"
        ) from exc
    if required and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise HistoryError(
            "migration history integration check could not read git state: "
            + (detail or "git returned no detail")
        )
    return result


def _target_ref(repo: Path, integration_target: str) -> str:
    target = str(integration_target).strip()
    if not target:
        raise HistoryError("migration history integration target is empty")
    candidates = (
        (target,)
        if target.startswith("origin/")
        else (f"origin/{target}", target)
    )
    for candidate in candidates:
        result = _git(
            repo,
            "rev-parse",
            "--verify",
            f"{candidate}^{{commit}}",
            required=False,
        )
        if result.returncode == 0:
            return candidate
    raise HistoryError(
        f"migration history integration target {target!r} cannot be resolved; "
        "the lane ordering cannot be proven"
    )


def _relative_modules_dir(modules_dir: str) -> str:
    path = PurePosixPath(str(modules_dir))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise HistoryError(
            "runner.config.modules_dir must be a repository-relative path for "
            "migration history integration checks"
        )
    return path.as_posix()


def _target_history(
    repo: Path,
    target_ref: str,
    modules_dir: str,
) -> tuple[HistoryIdentity, ...]:
    listing = _git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        target_ref,
        "--",
        modules_dir,
    ).stdout.decode("utf-8", "replace")
    directory = PurePosixPath(modules_dir)
    entries: list[HistoryIdentity] = []
    seen: dict[int, str] = {}
    for raw_path in listing.splitlines():
        path = PurePosixPath(raw_path.strip())
        if path.parent != directory or path.suffix != ".py":
            continue
        match = ENTRY_NAME_PATTERN.fullmatch(path.stem)
        if match is None:
            continue
        sequence = int(match.group(1))
        if sequence in seen:
            raise HistoryError(
                f"integration target migration history has duplicate sequence "
                f"{match.group(1)}: {seen[sequence]!r} and {path.stem!r}"
            )
        seen[sequence] = path.stem
        content = _git(repo, "show", f"{target_ref}:{path.as_posix()}").stdout
        entries.append(
            HistoryIdentity(sequence, path.stem, raw_content_sha256(content))
        )
    return tuple(sorted(entries, key=lambda entry: entry.sequence))


def _lane_history(repo: Path, modules_dir: str) -> tuple[HistoryIdentity, ...]:
    return tuple(
        HistoryIdentity(entry.sequence, entry.name, entry.content_sha256)
        for entry in ordinal_entries(repo / modules_dir)
    )


def _digest_pins(
    repo: Path,
    *,
    target_ref: str,
    modules_dir: str,
) -> dict[str, str]:
    """Return frozen pins, preferring the integration target's manifest.

    A lane manifest is considered only while bootstrapping the manifest into
    a target that has none. After that first merge, a lane cannot rewrite a
    pin to authorize its own history edit because the target copy wins.
    """
    manifest_path = f"{modules_dir}/{RELEASED_DIGESTS_NAME}"
    target = _git(
        repo,
        "show",
        f"{target_ref}:{manifest_path}",
        required=False,
    )
    if target.returncode == 0:
        raw = target.stdout
        source = f"{target_ref}:{manifest_path}"
    else:
        lane_path = repo / modules_dir / RELEASED_DIGESTS_NAME
        if not lane_path.is_file():
            return {}
        raw = lane_path.read_bytes()
        source = str(lane_path)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoryError(f"released migration digest manifest {source} is invalid: {exc}") from exc
    if not isinstance(payload, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str)
        for name, digest in payload.items()
    ):
        raise HistoryError(
            f"released migration digest manifest {source} must map names to digests"
        )
    return payload


def _is_frozen_content_restoration(
    target: HistoryIdentity,
    lane: HistoryIdentity,
    pins: dict[str, str],
) -> bool:
    """Whether *lane* restores one target entry to its released raw bytes."""
    return (
        lane.sequence == target.sequence
        and lane.name == target.name
        and pins.get(lane.name) == lane.content_sha256
    )


def _extension(
    *,
    worktree_path: Path,
    modules_dir: str,
    integration_target: str,
    migration_modules: Iterable[str],
) -> tuple[tuple[HistoryIdentity, ...], tuple[HistoryIdentity, ...], str]:
    declared = _numbered_identifiers(migration_modules)
    if not declared:
        return (), (), str(integration_target)
    relative_dir = _relative_modules_dir(modules_dir)
    target_ref = _target_ref(worktree_path, integration_target)
    target = _target_history(worktree_path, target_ref, relative_dir)
    lane = _lane_history(worktree_path, relative_dir)
    pins = _digest_pins(
        worktree_path,
        target_ref=target_ref,
        modules_dir=relative_dir,
    )
    lane_names = {entry.name for entry in lane}
    missing = [name for name in declared if name not in lane_names]
    if missing:
        raise HistoryError(
            f"lane migration history is missing declared entries: {missing}"
        )
    if len(lane) < len(target):
        raise HistoryError(
            f"lane migration history does not extend {target_ref}: target has "
            f"{len(target)} numbered entries but the lane has {len(lane)}"
        )
    for index, target_entry in enumerate(target):
        lane_entry = lane[index]
        if lane_entry != target_entry and not _is_frozen_content_restoration(
            target_entry,
            lane_entry,
            pins,
        ):
            raise HistoryError(
                f"lane migration history does not extend {target_ref}: target "
                f"entry {target_entry.name!r} is replaced by {lane_entry.name!r} "
                "or carries different permanent bytes"
            )
    return target, lane, target_ref


def require_rehearsal_history_extension(
    *,
    worktree_path: Path,
    modules_dir: str,
    integration_target: str,
    migration_modules: Iterable[str],
) -> None:
    """Refuse rehearsal unless the lane preserves the target's full history."""
    _extension(
        worktree_path=worktree_path,
        modules_dir=modules_dir,
        integration_target=integration_target,
        migration_modules=migration_modules,
    )


def require_merge_history_extension(
    *,
    worktree_path: Path,
    modules_dir: str,
    integration_target: str,
    migration_modules: Iterable[str],
) -> None:
    """Require every lane-only entry to be the target's next ordinal."""
    target, lane, target_ref = _extension(
        worktree_path=worktree_path,
        modules_dir=modules_dir,
        integration_target=integration_target,
        migration_modules=migration_modules,
    )
    if not lane:
        return
    expected = (target[-1].sequence + 1) if target else 1
    for entry in lane[len(target):]:
        if entry.sequence != expected:
            raise HistoryError(
                f"merge refused: new migration entry {entry.name!r} has ordinal "
                f"{entry.sequence}; {target_ref} requires exactly {expected} next"
            )
        expected += 1


__all__ = [
    "HistoryIdentity",
    "RELEASED_DIGESTS_NAME",
    "migration_ordinal",
    "require_merge_history_extension",
    "require_rehearsal_history_extension",
]
