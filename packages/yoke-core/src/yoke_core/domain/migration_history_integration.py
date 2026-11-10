"""Prove that a lane's numbered migration history extends its target."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from yoke_core.domain.migration_baseline import baseline_from_source

from yoke_core.domain.migration_content_identity import raw_content_sha256
from yoke_core.domain.migration_history import (
    ENTRY_NAME_PATTERN,
    HistoryError,
    ordinal_entries,
)


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


def resolve_target_ref(repo: Path, integration_target: str) -> str:
    target = str(integration_target).strip()
    if not target:
        raise HistoryError("migration history integration target is empty")
    candidates = (
        (target,) if target.startswith("origin/") else (f"origin/{target}", target)
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


def _listed_entries(
    repo: Path,
    ref: str,
    modules_dir: str,
) -> tuple[tuple[int, PurePosixPath], ...]:
    """Entry ordinals and paths in the history at *ref*, in sequence order."""
    listing = _git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        modules_dir,
    ).stdout.decode("utf-8", "replace")
    directory = PurePosixPath(modules_dir)
    listed: list[tuple[int, PurePosixPath]] = []
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
                f"migration history at {ref} has duplicate sequence "
                f"{match.group(1)}: {seen[sequence]!r} and {path.stem!r}. "
                "A new entry takes the next unused number: renumber the "
                "entry that has not been applied anywhere yet"
            )
        seen[sequence] = path.stem
        listed.append((sequence, path))
    return tuple(sorted(listed, key=lambda entry: entry[0]))


def history_names_at_ref(
    repository: Path,
    ref: str,
    modules_dir: str,
) -> tuple[str, ...]:
    """Ordered entry names the history at one exact revision carries.

    Names alone, so a caller asking only "which entries does this build
    carry?" reads the tree and baseline metadata, without reading each script. The
    name is the entry's ledger and fleet-receipt identity, so it is the
    whole answer to that question.
    """
    directory = _relative_modules_dir(modules_dir)
    live = [
        (sequence, path.stem)
        for sequence, path in _listed_entries(repository, ref, directory)
    ]
    folded = [
        (entry.sequence, entry.name)
        for entry in _baseline_at_ref(repository, ref, directory)
    ]
    return tuple(name for _, name in sorted(live + folded))


def _baseline_at_ref(repo: Path, ref: str, modules_dir: str):
    source = _git(repo, "show", f"{ref}:{modules_dir}/__init__.py", required=False)
    if source.returncode == 0:
        baseline = baseline_from_source(source.stdout, Path(modules_dir))
        if baseline is not None:
            return (baseline,)
    return ()


def _target_history(
    repo: Path,
    target_ref: str,
    modules_dir: str,
) -> tuple[HistoryIdentity, ...]:
    live = tuple(
        HistoryIdentity(
            sequence,
            path.stem,
            raw_content_sha256(
                _git(repo, "show", f"{target_ref}:{path.as_posix()}").stdout
            ),
        )
        for sequence, path in _listed_entries(repo, target_ref, modules_dir)
    )

    folded = tuple(
        HistoryIdentity(entry.sequence, entry.name, entry.content_sha256)
        for entry in _baseline_at_ref(repo, target_ref, modules_dir)
    )
    return tuple(sorted(live + folded, key=lambda entry: entry.sequence))


def _lane_history(repo: Path, modules_dir: str) -> tuple[HistoryIdentity, ...]:
    return tuple(
        HistoryIdentity(entry.sequence, entry.name, entry.content_sha256)
        for entry in ordinal_entries(repo / modules_dir)
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
    target_ref = resolve_target_ref(worktree_path, integration_target)
    target = _target_history(worktree_path, target_ref, relative_dir)
    lane = _lane_history(worktree_path, relative_dir)
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
        if lane_entry != target_entry:
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
    """Require the target history, including the code-declared baseline."""
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
    for entry in lane[len(target) :]:
        if entry.sequence != expected:
            raise HistoryError(
                f"merge refused: new migration entry {entry.name!r} has ordinal "
                f"{entry.sequence}; {target_ref} requires exactly {expected} next"
            )
        expected += 1


__all__ = [
    "HistoryIdentity",
    "history_names_at_ref",
    "migration_ordinal",
    "resolve_target_ref",
    "require_merge_history_extension",
    "require_rehearsal_history_extension",
]
