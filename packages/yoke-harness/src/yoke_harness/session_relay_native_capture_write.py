"""Replace a private capture atomically so readers see one complete envelope."""

from pathlib import Path
import os
import stat

from yoke_contracts.owner_private_path import (
    is_owner_private_directory, is_owner_private_file, write_owner_private,
)


def replace_private_capture(path: Path, payload: bytes) -> None:
    """Validate the target before publishing one owner-only snapshot."""
    from yoke_harness.session_relay_native_diagnostics import NativeDiagnosticError

    if path.exists() or path.is_symlink():
        details = path.lstat()
        owned = is_owner_private_file(path)
        if os.name != "nt" and is_owner_private_directory(path.parent):
            owned = details.st_uid == path.parent.stat().st_uid
        if not stat.S_ISREG(details.st_mode) or not owned:
            raise NativeDiagnosticError("diagnostic target is unsafe")
    try:
        write_owner_private(path, payload)
    except OSError as exc:
        raise NativeDiagnosticError(
            "diagnostic could not be replaced; inspect capture directory permissions and retry"
        ) from exc
