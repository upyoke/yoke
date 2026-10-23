"""Remove retired golden snapshots after the new one is registered.

Restore reads only the registered baseline, so older snapshots are not a
rollback copy. A directory named for the test user is that user's golden
root: every other child is a snapshot, including dated homes, mixed captures,
``.yoke-golden-*`` temporaries and retired browser profiles. A shared parent
drops only this user's ``USER-home-*`` and ``home-*`` snapshots, so another
user's baseline stays. One machine can be registered in several projects
that share a parent, so every golden registered for this machine stays with
its ``.probes``, ``.manifest`` and ``.harness-clis`` sidecars. A symlink, or a
name whose removal fails, is kept and named while the rest still go.
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, Sequence

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
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


def removal_order(names: Sequence[str]) -> tuple[str, ...]:
    """Put every sidecar before any folder, so no sidecar outlives its golden."""
    return tuple(sorted(names, key=lambda name: not name.endswith(SIDECAR_SUFFIXES)))


def removal_script(parent: str, names: Sequence[str]) -> str:
    """Return a POSIX script that deletes only the named direct children.

    A failed name is kept and the loop goes on; each name prints ``removed N``
    or ``kept N REASON`` (``N`` is its 1-based position), and any kept name
    exits 1. A symlink is kept, never followed. Capture seals a golden with
    macOS deny-delete ACLs, so ACLs are cleared (``chmod -N``, macOS only)
    and directories made owner-writable before ``rm``.
    """
    quoted = " ".join(shlex.quote(name) for name in names)
    return "\n".join(
        (
            "set -u",
            "kept=0 index=0",
            f"parent={shlex.quote(parent)}",
            f"for name in {quoted}; do",
            "  index=$((index + 1))",
            '  case "$name" in ""|"."|".."|*/*) printf "kept %s rejected\\n" "$index"; kept=1; continue ;; esac',
            '  target="$parent/$name"',
            '  if [ -L "$target" ]; then printf "kept %s symlink\\n" "$index"; kept=1; continue; fi',
            "  if (",
            '    if [ -d "$target" ]; then chmod -RN "$target" 2>/dev/null',
            '      chmod -R u+rwx "$target" && rm -rf -- "$target"',
            '    else chmod -N "$target" 2>/dev/null; rm -f -- "$target"; fi',
            "  ); then",
            '    printf "removed %s\\n" "$index"',
            "  else",
            '    printf "kept %s failed\\n" "$index"',
            "    kept=1",
            "  fi",
            "done",
            'exit "$kept"',
        )
    )


def removal_outcome(names: Sequence[str], stdout: str) -> tuple[list[str], list[str]]:
    """Split ``removal_script`` output into removed names and kept names with reasons."""
    reported: dict[int, str] = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in {"removed", "kept"} and parts[1].isdigit():
            reason = parts[0] if parts[0] == "removed" else (parts[2:] or ["failed"])[0]
            reported[int(parts[1]) - 1] = reason
    removed = [name for i, name in enumerate(names) if reported.get(i) == "removed"]
    kept = [
        f"{name} ({reported.get(i, 'unreported')})"
        for i, name in enumerate(names)
        if reported.get(i) != "removed"
    ]
    return removed, kept


def retention_summary(removed: Sequence[str], kept: Sequence[str]) -> str:
    """Name what retention removed and kept, for capture and refresh output."""
    return (
        f"Removed: {', '.join(removed) or 'none'}. Kept: {', '.join(kept) or 'none'}."
    )


def _recovery(destination: str, parent: str) -> str:
    return (
        f"The registered golden {destination} is already recorded. "
        f"Remove every other snapshot under {parent}, but keep {destination}, "
        "every golden another project registered for this machine (yoke "
        "test-machine get --project P --test-machine TEST_MACHINE names it as "
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
    ordered = removal_order(removable)
    result = run(removal_script(parent, ordered), timeout=300)
    removed, kept = removal_outcome(ordered, result.stdout or "")
    if kept or getattr(result, "returncode", 1) != 0:
        detail = bounded_machine_qa_diagnostic(result.stderr or "")
        raise SnapshotRetentionError(
            f"Retired snapshots under {parent} were not all removed. "
            + retention_summary(removed, kept)
            + (f" {detail}" if detail else ""),
            _recovery(destination, parent),
        )
    return removed


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
    "removal_order",
    "removal_outcome",
    "removal_script",
    "retain_after_verified_capture",
    "retain_registered_golden",
    "retention_summary",
]
