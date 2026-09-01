"""The bundle's owner-only landing place for a universe's first admin token.

The file is created empty by ``yoke self-host init`` so it exists, owned by
the operator at mode 0600, before any container touches it — Compose
bind-mounts a path that does not exist as a root-owned directory, and a
descriptor the root bootstrap opens onto an operator-owned file is what
lets the unprivileged server write a credential the operator can still
read. Nothing in the container ever creates or chowns it.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.self_host import protection
from yoke_cli.self_host.secure_layout import SECRETS_DIR_NAME
from yoke_contracts.self_host_bootstrap_output import is_api_token

FIRST_BOOT_TOKEN_FILE_NAME = "first-boot-admin-token"


class FirstBootTokenError(RuntimeError):
    """The bundle's first-boot token file is missing or unusable."""


def token_drop_path(bundle_dir: Path | str) -> Path:
    """Bundle-relative host path of the first-boot token file."""
    return Path(bundle_dir) / SECRETS_DIR_NAME / FIRST_BOOT_TOKEN_FILE_NAME


def ensure_token_drop(bundle_dir: Path | str) -> bool:
    """Create the empty owner-only token file when it is absent.

    Returns whether this call created it. Never truncates an existing file:
    a bundle whose universe was already born holds the only copy of its
    credential here until the operator removes it.
    """
    target = token_drop_path(bundle_dir)
    if target.exists():
        return False
    protection.atomic_replace_bytes(target, b"", mode=0o600)
    return True


def require_token_drop(bundle_dir: Path | str) -> Path:
    """Return the token file path, refusing a bundle that lacks it."""
    target = token_drop_path(bundle_dir)
    if not target.is_file():
        raise FirstBootTokenError(
            f"self-host bundle has no first-boot token file at {target}; "
            f"create it with `yoke self-host init --dir {bundle_dir} "
            "--protect-existing`"
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
    "ensure_token_drop",
    "read_first_boot_token",
    "require_token_drop",
    "token_drop_path",
]
