"""The host command durably writes the first admin token, never the container."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.self_host.secure_layout import SECRETS_DIR_NAME
from yoke_contracts.self_host_bootstrap_output import is_api_token

FIRST_BOOT_TOKEN_FILE_NAME = "first-boot-admin-token"


class FirstBootTokenError(RuntimeError):
    """The bundle's first-boot token file is missing or unusable."""


def token_drop_path(bundle_dir: Path | str) -> Path:
    """Bundle-relative host path of the first-boot token file."""
    return Path(bundle_dir) / SECRETS_DIR_NAME / FIRST_BOOT_TOKEN_FILE_NAME


def require_token_drop(bundle_dir: Path | str) -> Path:
    """Return the token file path, refusing a bundle that lacks it."""
    target = token_drop_path(bundle_dir)
    if not target.is_file():
        raise FirstBootTokenError(
            f"self-host bundle has no first-boot token file at {target}; "
            f"start with `yoke self-host init --dir {bundle_dir} "
            "--protect-existing --start`"
        )
    return target


def read_first_boot_token(bundle_dir: Path | str) -> str | None:
    """Return the delivered token, or ``None`` while the file is still empty."""
    try:
        candidate = token_drop_path(bundle_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return candidate if is_api_token(candidate) else None


__all__ = [
    "FIRST_BOOT_TOKEN_FILE_NAME",
    "FirstBootTokenError",
    "read_first_boot_token",
    "require_token_drop",
    "token_drop_path",
]
