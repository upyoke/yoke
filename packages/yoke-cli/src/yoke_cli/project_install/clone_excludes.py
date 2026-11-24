"""Git clone-local ignore entries and the install ownership they carry."""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

from yoke_cli.project_install import checkout_gate
from yoke_contracts.filesystem_safety import atomic_replace_bytes
from yoke_contracts.machine_config.checkout import LANES_DIR
from yoke_contracts.project_contract.install_error import ProjectInstallError
from yoke_contracts.refusal_recovery import compose_refusal

KEY = "clone_excludes"
ENTRIES = (f"/{LANES_DIR}/", "/.claude/settings.local.json")


def validate_entries(value: object, *, source: str) -> None:
    if (
        not isinstance(value, list)
        or any(entry not in ENTRIES for entry in value)
        or len(value) != len(set(value))
    ):
        raise ProjectInstallError(f"{source} {KEY} must list unique Yoke clone excludes")


def _refusal(path: Path, reason: object) -> ProjectInstallError:
    return ProjectInstallError(
        compose_refusal(
            f"clone_exclude_unwritable: {path}: {reason}",
            recovery="Repair Git metadata or permissions, then rerun yoke project install.",
        )
    )


def _path(root: Path) -> Path:
    expected = root / ".git/info/exclude"
    try:
        result = checkout_gate.run_git(root, "rev-parse", "--git-path", "info/exclude")
    except (OSError, UnicodeError) as exc:
        raise _refusal(expected, exc) from exc
    if result.returncode or not result.stdout.strip():
        raise _refusal(expected, result.stderr.strip() or "Git returned no exclude path")
    return root / Path(result.stdout.strip())


def _read(path: Path) -> bytes:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError("expected a regular Git exclude file")
        return path.read_bytes()
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise _refusal(path, exc) from exc


def _write(path: Path, data: bytes) -> None:
    try:
        if path.exists():
            # Atomic replacement alone could bypass a read-only file's mode.
            with path.open("r+b"):
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(path, data)
    except OSError as exc:
        raise _refusal(path, exc) from exc


def _missing(data: bytes, entries: tuple[str, ...]) -> list[str]:
    lines = data.splitlines()
    return [entry for entry in entries if entry.encode() not in lines]


def preview(root: Path) -> list[str]:
    if not checkout_gate.is_git_checkout(root):
        return []
    return _missing(_read(_path(root)), ENTRIES)


def append(
    root: Path, entries: tuple[str, ...], *, before_write: Callable[[list[str]], None] | None = None
) -> list[str]:
    path = _path(root)
    data = _read(path)
    added = _missing(data, entries)
    if before_write is not None:
        before_write(added)
    if added:
        newline = b"\r\n" if b"\r\n" in data else b"\n"
        separator = newline if data and not data.endswith(b"\n") else b""
        _write(path, data + separator + b"".join(entry.encode() + newline for entry in added))
    return added


def remove(root: Path, owned: list[str], *, check: bool = False) -> list[str]:
    if not owned:
        return []
    path = _path(root)
    data = _read(path)
    pending = {entry.encode() for entry in owned}
    removed = []
    kept = []
    for line in data.splitlines(keepends=True):
        entry = line.rstrip(b"\r\n")
        if entry in pending:
            pending.remove(entry)
            removed.append(entry.decode())
        else:
            kept.append(line)
    if removed:
        if check:
            try:
                with path.open("r+b"):
                    pass
            except OSError as exc:
                raise _refusal(path, exc) from exc
        else:
            _write(path, b"".join(kept))
    return removed
