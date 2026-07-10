"""Owner-controlled directory boundary for a self-host bundle."""

from __future__ import annotations

import os
from pathlib import Path
import stat


SECRETS_DIRECTORY_MODE = 0o700


class SecureLayoutError(RuntimeError):
    """The self-host bundle directory boundary is unsafe."""


def prepare_bundle_layout(target: Path, *, create: bool) -> None:
    """Validate the real bundle and owner-only ``secrets`` directories."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or not hasattr(os, "geteuid"):
        raise SecureLayoutError(
            "platform cannot safely open owner-controlled self-host directories"
        )
    if create:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecureLayoutError(
                f"could not create self-host bundle directory {target}: {exc}"
            ) from exc

    bundle_descriptor = _open_real_directory(
        target,
        flags=nofollow,
        role="bundle",
    )
    try:
        _assert_owner_controlled_bundle(bundle_descriptor, target)
        secrets_descriptor = _open_secrets_directory(
            target,
            bundle_descriptor=bundle_descriptor,
            flags=nofollow,
            create=create,
        )
        os.close(secrets_descriptor)
    finally:
        os.close(bundle_descriptor)


def validate_existing_bundle_files(
    target: Path,
    *,
    public_names: tuple[str, ...],
    secret_names: tuple[str, ...],
) -> None:
    """Validate existing config and credential files without following links."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise SecureLayoutError(
            "platform cannot safely validate existing self-host bundle files"
        )
    bundle_descriptor = _open_real_directory(
        target,
        flags=nofollow,
        role="bundle",
    )
    try:
        _assert_owner_controlled_bundle(bundle_descriptor, target)
        for name in public_names:
            _validate_regular_file(
                bundle_descriptor,
                name,
                path=target / name,
                owner_only=False,
                flags=nofollow,
            )
        secrets_descriptor = _open_secrets_directory(
            target,
            bundle_descriptor=bundle_descriptor,
            flags=nofollow,
            create=False,
        )
        try:
            for name in secret_names:
                _validate_regular_file(
                    secrets_descriptor,
                    name,
                    path=target / "secrets" / name,
                    owner_only=True,
                    flags=nofollow,
                )
        finally:
            os.close(secrets_descriptor)
    finally:
        os.close(bundle_descriptor)


def _open_real_directory(path: Path, *, flags: int, role: str) -> int:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SecureLayoutError(
            f"self-host {role} directory is missing or unreadable: {path}"
        ) from exc
    if not stat.S_ISDIR(before.st_mode):
        raise SecureLayoutError(
            f"self-host {role} path must be a real directory, not a symlink: {path}"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | flags,
        )
        after = os.fstat(descriptor)
        if not stat.S_ISDIR(after.st_mode) or (before.st_dev, before.st_ino) != (
            after.st_dev,
            after.st_ino,
        ):
            raise SecureLayoutError(
                f"self-host {role} directory changed during validation: {path}"
            )
        return descriptor
    except SecureLayoutError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise SecureLayoutError(
            f"could not safely open self-host {role} directory {path}: {exc}"
        ) from exc


def _assert_owner_controlled_bundle(descriptor: int, path: Path) -> None:
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise SecureLayoutError(
            "self-host bundle directory must be owned by the current user "
            f"and not group/world writable: {path}"
        )


def _open_secrets_directory(
    target: Path,
    *,
    bundle_descriptor: int,
    flags: int,
    create: bool,
) -> int:
    name = "secrets"
    created = False
    try:
        before = os.stat(
            name,
            dir_fd=bundle_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        if not create:
            raise SecureLayoutError(
                f"self-host secrets directory is missing: {target / name}"
            ) from None
        try:
            os.mkdir(
                name,
                mode=SECRETS_DIRECTORY_MODE,
                dir_fd=bundle_descriptor,
            )
            created = True
            before = os.stat(
                name,
                dir_fd=bundle_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SecureLayoutError(
                f"could not create self-host secrets directory {target / name}: {exc}"
            ) from exc
    except OSError as exc:
        raise SecureLayoutError(
            f"could not inspect self-host secrets directory {target / name}: {exc}"
        ) from exc

    if not stat.S_ISDIR(before.st_mode):
        raise SecureLayoutError(
            "self-host secrets path must be a real directory, not a symlink: "
            f"{target / name}"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | flags,
            dir_fd=bundle_descriptor,
        )
        if created:
            os.fchmod(descriptor, SECRETS_DIRECTORY_MODE)
        after = os.fstat(descriptor)
        if not stat.S_ISDIR(after.st_mode) or (before.st_dev, before.st_ino) != (
            after.st_dev,
            after.st_ino,
        ):
            raise SecureLayoutError(
                f"self-host secrets directory changed during validation: {target / name}"
            )
        if (
            after.st_uid != os.geteuid()
            or stat.S_IMODE(after.st_mode) != SECRETS_DIRECTORY_MODE
        ):
            raise SecureLayoutError(
                "self-host secrets directory must be owned by the current "
                f"user with mode 0700: {target / name}; run `chmod 700 "
                f"{target / name}` and retry"
            )
        return descriptor
    except SecureLayoutError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise SecureLayoutError(
            f"could not safely open self-host secrets directory {target / name}: {exc}"
        ) from exc


def _validate_regular_file(
    directory_descriptor: int,
    name: str,
    *,
    path: Path,
    owner_only: bool,
    flags: int,
) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | flags,
            dir_fd=directory_descriptor,
        )
        info = os.fstat(descriptor)
    except OSError as exc:
        raise SecureLayoutError(
            "existing self-host bundle is incomplete or contains a symlink "
            f"instead of a regular file: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise SecureLayoutError(
            f"existing self-host bundle path must be a regular file: {path}"
        )
    if owner_only and (info.st_uid != os.geteuid() or info.st_nlink != 1):
        raise SecureLayoutError(
            "existing self-host credential must be a current-owner, "
            f"single-link regular file: {path}; replace unsafe links or "
            "ownership, then retry"
        )
    if owner_only and stat.S_IMODE(info.st_mode) & 0o077:
        raise SecureLayoutError(
            "existing self-host credential must have no group/world access: "
            f"{path}; run "
            f"`chmod 600 {path}` and retry"
        )


__all__ = [
    "SECRETS_DIRECTORY_MODE",
    "SecureLayoutError",
    "prepare_bundle_layout",
    "validate_existing_bundle_files",
]
