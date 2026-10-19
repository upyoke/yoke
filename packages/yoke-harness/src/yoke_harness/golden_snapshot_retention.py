"""Remove retired golden snapshots after the new one is registered.

Restore reads only the registered baseline, so older snapshots are not a
rollback copy. A directory named for the test user is that user's golden
root: every other child is a snapshot, including dated homes, mixed captures,
``.yoke-golden-*`` temporaries and retired browser profiles. A shared parent
drops only this user's ``USER-home-*`` and ``home-*`` snapshots, so another
user's baseline stays. One machine can be registered in several projects
that share a parent, so every golden the server names as registered for this
machine stays, with its ``.probes``, ``.manifest`` and ``.harness-clis`` sidecars, whichever
project registered it. A symlink is never removed.
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, Sequence

from yoke_contracts.machine_qa_host_control import (
    KEPT_GOLDEN_PATHS_KEY,
    KEPT_GOLDEN_PATHS_UNKNOWN_KEY,
)

RETENTION_FAILED = "golden_snapshot_retention_failed"
SIDECAR_SUFFIXES = (".probes", ".manifest", ".harness-clis")
LINUX_CAPTURE_SPACE_CHECK = """\
    try:
        free = shutil.disk_usage(baseline.parent).free
        expected = sum(
            p.stat().st_size
            for p in home.rglob("*")
            if not p.is_symlink() and p.is_file()
        )
    except OSError as exc:
        refuse(
            "golden_capture_space_check_failed",
            recovery=(
                "Repair access to the home and the golden directory, then "
                "retry: yoke test-machine golden-capture ("
                + str(getattr(exc, "strerror", None) or exc)
                + ")"
            ),
        )
    if free < expected:
        refuse(
            "golden_capture_insufficient_space",
            free_bytes=free,
            expected_bytes=expected,
            recovery=(
                "Remove every snapshot under "
                + str(baseline.parent)
                + " except each project's registered golden for this "
                "machine (yoke test-machine get shows golden_baseline_path) "
                "and their .probes, .manifest and .harness-clis files, then retry: yoke "
                "test-machine golden-capture"
            ),
        )
"""


class SnapshotRetentionError(Exception):
    """The new golden is registered and retired snapshots are still present."""

    def __init__(self, detail: str, recovery: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = RETENTION_FAILED
        self.recovery = recovery


def kept_snapshot_names(registered_names: Sequence[str]) -> frozenset[str]:
    """Return every registered golden and the sidecars restore still reads."""
    return frozenset(
        name + suffix for name in registered_names for suffix in ("", *SIDECAR_SUFFIXES)
    )


def removable_snapshot_names(
    names: Sequence[str],
    *,
    registered_names: Sequence[str],
    user: str,
    parent_name: str,
) -> tuple[str, ...]:
    """Return sibling snapshot names that are safe to delete."""
    kept = kept_snapshot_names(registered_names)
    per_user_root = parent_name == user
    removable: list[str] = []
    for name in names:
        if name in kept or name in {"", ".", ".."} or "/" in name:
            continue
        if _is_retired_snapshot(name, user=user, per_user_root=per_user_root):
            removable.append(name)
    return tuple(removable)


def _is_retired_snapshot(name: str, *, user: str, per_user_root: bool) -> bool:
    if per_user_root or name.startswith(".yoke-golden-"):
        return True
    stem = name
    for suffix in SIDECAR_SUFFIXES:
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    return stem.startswith(f"{user}-home-") or stem.startswith("home-")


def names_from_find(parent: str, output: str) -> tuple[str, ...]:
    """Return direct-child names from ``find -print0`` output."""
    root = PurePosixPath(parent)
    names: list[str] = []
    for raw in output.split("\0"):
        if not raw:
            continue
        path = PurePosixPath(raw)
        if path.parent != root or path.name in {"", ".", ".."}:
            continue
        names.append(path.name)
    return tuple(names)


def removal_script(parent: str, names: Sequence[str]) -> str:
    """Return a POSIX script that deletes only the named direct children.

    Symlinks are refused before any removal, so a link is never followed.
    """
    quoted = " ".join(shlex.quote(name) for name in names)
    return "\n".join(
        (
            "set -eu",
            "skipped=0",
            f"parent={shlex.quote(parent)}",
            f"for name in {quoted}; do",
            '  case "$name" in ""|"."|".."|*/*) printf "%s\\n" "rejected $name"; exit 1 ;; esac',
            '  target="$parent/$name"',
            '  if [ -L "$target" ]; then printf "%s\\n" "symlink $target"; skipped=1; continue; fi',
            '  if [ -d "$target" ]; then rm -rf -- "$target"; elif [ -e "$target" ]; then rm -f -- "$target"; fi',
            "done",
            'exit "$skipped"',
        )
    )


def _recovery(destination: str, parent: str) -> str:
    return (
        f"The registered golden {destination} is already recorded. "
        f"Remove every other snapshot under {parent}, but keep {destination}, "
        "every golden another project registered for this machine (yoke "
        "test-machine get --project P --machine NAME names it as "
        "golden_baseline_path), and their .probes, .manifest "
        "and .harness-clis files. Do not capture again until those leftovers are gone."
    )


def apply_retention(
    run: Any,
    *,
    destination: str,
    user: str,
    kept_paths: Sequence[str],
) -> list[str]:
    """List ``destination``'s parent through ``run`` and delete retired snapshots.

    ``kept_paths`` are every golden registered for this machine; each one in
    this parent stays.
    """
    parent_path = PurePosixPath(destination).parent
    parent = parent_path.as_posix()
    registered = PurePosixPath(destination).name
    registered_names = {registered} | {
        PurePosixPath(path).name
        for path in kept_paths
        if PurePosixPath(path).parent == parent_path
    }
    if parent == "/" or not user or registered in {"", ".", ".."}:
        raise SnapshotRetentionError(
            f"Refusing to clean an unsafe golden parent for {destination}.",
            _recovery(destination, parent),
        )
    listed = run(
        f"find {shlex.quote(parent)} -mindepth 1 -maxdepth 1 -print0",
        timeout=60,
    )
    if getattr(listed, "returncode", 1) != 0:
        raise SnapshotRetentionError(
            f"Could not list snapshots under {parent}.",
            _recovery(destination, parent),
        )
    removable = removable_snapshot_names(
        names_from_find(parent, listed.stdout or ""),
        registered_names=sorted(registered_names),
        user=user,
        parent_name=parent_path.name,
    )
    if not removable:
        return []
    removed = run(removal_script(parent, removable), timeout=300)
    if getattr(removed, "returncode", 1) != 0:
        detail = (removed.stdout or removed.stderr or "").strip()
        raise SnapshotRetentionError(
            f"Retired snapshots under {parent} were not removed."
            + (f" {detail}" if detail else ""),
            _recovery(destination, parent),
        )
    return list(removable)


def retain_after_verified_capture(
    operation: str,
    success: bool,
    result: dict[str, Any] | None,
    execution: dict[str, Any],
) -> list[str] | None:
    """Delete retired snapshots after a verified golden capture is registered."""
    payload = result or {}
    destination = payload.get("golden_baseline_path")
    if not (
        operation == "golden_capture"
        and success
        and payload.get("status") == "verified"
        and isinstance(destination, str)
        and destination
    ):
        return None
    parent = str(PurePosixPath(destination).parent)
    unknown = payload.get(KEPT_GOLDEN_PATHS_UNKNOWN_KEY)
    if isinstance(unknown, str) and unknown:
        raise SnapshotRetentionError(
            f"Retired snapshots under {parent} were kept: {unknown}.",
            _recovery(destination, parent),
        )
    kept_paths = payload.get(KEPT_GOLDEN_PATHS_KEY)
    if not isinstance(kept_paths, list) or destination not in kept_paths:
        raise SnapshotRetentionError(
            f"Retired snapshots under {parent} were kept: this server does not "
            "name the goldens other projects registered for this machine "
            f"({KEPT_GOLDEN_PATHS_KEY}), so deleting could remove one of them. "
            "Retention needs a server from the release that adds that field.",
            _recovery(destination, parent),
        )
    return retain_registered_golden(execution, destination, kept_paths)


def retain_registered_golden(
    execution: dict[str, Any],
    destination: str,
    kept_paths: Sequence[str],
) -> list[str]:
    """Open the capture's host and delete snapshots no project registered."""
    from yoke_contracts.machine_qa_execution import HostControlExecutionContract
    from yoke_harness.host_operations import host_operations_for

    try:
        contract = HostControlExecutionContract.model_validate(execution)
    except Exception as exc:
        raise SnapshotRetentionError(
            "The capture contract could not be read to remove retired snapshots.",
            _recovery(destination, str(PurePosixPath(destination).parent)),
        ) from exc
    if contract.golden_destination != destination:
        raise SnapshotRetentionError(
            f"Registered golden {destination} does not match the capture destination.",
            _recovery(destination, str(PurePosixPath(destination).parent)),
        )
    try:
        operations = host_operations_for(contract)
        return apply_retention(
            operations._run,
            destination=destination,
            user=str(contract.settings["user"]),
            kept_paths=kept_paths,
        )
    except SnapshotRetentionError:
        raise
    except Exception as exc:
        raise SnapshotRetentionError(
            "Retired snapshots could not be removed after "
            f"{destination} was registered ({type(exc).__name__}).",
            _recovery(destination, str(PurePosixPath(destination).parent)),
        ) from exc


__all__ = [
    "LINUX_CAPTURE_SPACE_CHECK",
    "RETENTION_FAILED",
    "SnapshotRetentionError",
    "apply_retention",
    "kept_snapshot_names",
    "names_from_find",
    "removable_snapshot_names",
    "removal_script",
    "retain_after_verified_capture",
    "retain_registered_golden",
]
