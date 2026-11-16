"""Replace a private capture atomically so readers see one complete envelope."""

from pathlib import Path

from yoke_contracts.owner_private_path import is_owner_private_file, write_owner_private


def replace_private_capture(path: Path, payload: bytes) -> None:
    """Validate the target before publishing one owner-only snapshot."""
    from yoke_harness.session_relay_native_diagnostics import NativeDiagnosticError

    if (path.exists() or path.is_symlink()) and not is_owner_private_file(path):
        raise NativeDiagnosticError("diagnostic target is unsafe")
    try:
        write_owner_private(path, payload)
    except OSError as exc:
        raise NativeDiagnosticError(
            "diagnostic could not be replaced; inspect capture directory permissions and retry"
        ) from exc
