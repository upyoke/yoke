"""Standalone program sent to a leased test host; requires only Python 3."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


MINIMUM_MISSION_FREE_BYTES = 1024**3
TEMP_PATTERNS = (
    "yoke-*",
    ".yoke-*",
    "claude-*",
    "codex-*",
    "cursor-*",
    "playwright*",
    "puppeteer*",
    "chrome*",
    "chromium*",
    ".org.chromium.*",
    ".com.google.Chrome.*",
    "scoped_dir*",
    "pip-*",
)


def temp_roots() -> list[Path]:
    roots = [Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())]
    if sys.platform == "darwin":
        for name in ("DARWIN_USER_TEMP_DIR", "DARWIN_USER_CACHE_DIR"):
            result = subprocess.run(
                ["/usr/bin/getconf", name],
                capture_output=True,
                text=True,
                check=True,
            )
            roots.append(Path(result.stdout.strip()))
    return list(dict.fromkeys(root.resolve() for root in roots if root.is_dir()))


def cleanup(roots: list[Path], protected: list[Path]) -> dict:
    """Clear only owned run artifacts, never following a symlink or mount."""
    protected = [path.resolve() for path in protected]
    uid = os.getuid()
    if uid == 0:
        raise ValueError("test_machine_temp_root_user_refused")
    devices = {root.stat().st_dev: root for root in roots}
    before = {device: shutil.disk_usage(root).free for device, root in devices.items()}
    candidates = []

    def select(entry: Path, device: int) -> None:
        if any(entry == path or path in entry.parents for path in protected):
            return
        info = entry.lstat()
        if info.st_uid != uid or info.st_dev != device:
            raise ValueError("test_machine_temp_ownership_refused")
        if not (
            stat.S_ISREG(info.st_mode)
            or stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
        ):
            return
        if any(entry in path.parents for path in protected):
            if stat.S_ISDIR(info.st_mode):
                for child in entry.iterdir():
                    select(child, device)
            return
        if stat.S_ISDIR(info.st_mode):

            def fail(error):
                raise error

            for current, directories, files in os.walk(
                entry, followlinks=False, onerror=fail
            ):
                for name in (*directories, *files):
                    child = (Path(current) / name).lstat()
                    if child.st_uid != uid or child.st_dev != device:
                        raise ValueError("test_machine_temp_ownership_refused")
        if not any(parent == entry or parent in entry.parents for parent in candidates):
            candidates.append(entry)

    for root in roots:
        if root == Path("/"):
            raise ValueError("test_machine_temp_root_refused")
        if any(root == path or path in root.parents for path in protected):
            continue
        for entry in root.iterdir():
            if not any(
                fnmatch.fnmatchcase(entry.name, pattern) for pattern in TEMP_PATTERNS
            ):
                continue
            info = entry.lstat()
            if info.st_uid != uid or not (
                stat.S_ISREG(info.st_mode)
                or stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
            ):
                continue
            # Validate before deleting; exclude the active mission's subtree,
            # while allowing stale siblings beneath the shared mission root.
            select(entry, root.stat().st_dev)
    for entry in candidates:
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        else:
            shutil.rmtree(entry)
    after = {device: shutil.disk_usage(root).free for device, root in devices.items()}
    return {
        "ok": True,
        "removed_entries": len(candidates),
        "freed_bytes": sum(max(0, after[key] - value) for key, value in before.items()),
        "free_bytes": min(after.values()),
    }


def disk_preflight(roots: list[Path], home: Path) -> dict:
    free = min(shutil.disk_usage(path).free for path in [*roots, home])
    return {
        "ok": free >= MINIMUM_MISSION_FREE_BYTES,
        "free_bytes": free,
        "minimum_free_bytes": MINIMUM_MISSION_FREE_BYTES,
        "error_code": None
        if free >= MINIMUM_MISSION_FREE_BYTES
        else "test_machine_disk_space_low",
    }


def main() -> None:
    try:
        operation, home, *protected = sys.argv[1:]
        roots = temp_roots()
        if operation == "cleanup":
            result = cleanup(roots, [Path(home), *(Path(value) for value in protected)])
        elif operation == "disk":
            result = disk_preflight(roots, Path(home))
        else:
            raise ValueError("test_machine_temp_operation_unknown")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = {
            "ok": False,
            "error_code": "test_machine_temp_operation_failed",
            "reason": str(error),
        }
    print(json.dumps(result))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
