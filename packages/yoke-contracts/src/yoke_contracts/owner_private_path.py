"""Cross-platform owner-private local path validation and atomic writes."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

if __package__:
    from yoke_contracts import windows_private_directory
else:
    import _yoke_windows_private_directory as windows_private_directory

_WINDOWS_PERMISSIONS = os.name == "nt"


def _is_private(path: str | Path, *, directory: bool) -> bool:
    selected = Path(path)
    try:
        info = selected.stat(follow_symlinks=False)
        if not (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode):
            return False
        if _WINDOWS_PERMISSIONS:
            check = (windows_private_directory.is_private_directory if directory
                     else windows_private_directory.is_private_file)
            return check(selected)
        if info.st_uid != os.getuid():
            return False
        return not bool(stat.S_IMODE(info.st_mode) & 0o077)
    except OSError:
        return False


def is_owner_private_file(path: str | Path) -> bool:
    """Return whether a regular file is accessible only to trusted principals."""
    return _is_private(path, directory=False)


def is_owner_private_directory(path: str | Path) -> bool:
    """Validate directory ownership and private mode or protected Windows DACL."""
    return _is_private(path, directory=True)


def create_owner_private_directory(path: str | Path) -> Path:
    """Create one private directory; refuse unsafe existing paths, create no parents."""
    selected = Path(path)
    try:
        if _WINDOWS_PERMISSIONS:
            windows_private_directory.create_private_directory(selected)
        else:
            selected.mkdir(mode=0o700)
    except FileExistsError:
        pass
    if not is_owner_private_directory(selected):
        raise OSError(f"owner_private_directory_unsafe: {selected}; repair ownership/access before retrying")
    return selected


def write_owner_private(path: str | Path, data: str | bytes) -> None:
    """Atomically replace a private file, without creating parents.

    Text is UTF-8. The same-directory temporary file is made private before any
    data is written, flushed and fsynced before replacement. Errors are OSError.
    """
    selected = Path(path)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    descriptor, temporary = tempfile.mkstemp(prefix=f".{selected.name}.", dir=selected.parent)
    temporary = Path(temporary)
    try:
        if _WINDOWS_PERMISSIONS:
            windows_private_directory.make_private_file(temporary)
        else:
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if not is_owner_private_file(temporary):
            raise OSError(f"owner_private_write_denied: {selected}; repair owner permissions and retry")
        os.replace(temporary, selected)
    except OSError as exc:
        raise OSError(f"owner_private_write_failed: {selected}; check parent access and close open destination handles: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


__all__ = ["is_owner_private_file", "is_owner_private_directory",
           "create_owner_private_directory", "write_owner_private"]
