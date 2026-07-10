"""Secret-protection helpers for an operator-managed self-host bundle."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
from typing import Iterable

from yoke_cli.self_host import atomic_file
from yoke_cli.self_host import secure_layout


GITIGNORE_MANAGED_BEGIN = "# >>> BEGIN YOKE SELF-HOST SECRET PROTECTION >>>"
GITIGNORE_MANAGED_END = "# <<< END YOKE SELF-HOST SECRET PROTECTION <<<"
GITIGNORE_MANAGED_BLOCK = (
    f"{GITIGNORE_MANAGED_BEGIN}\n"
    "# Managed by Yoke; operator rules outside this block are preserved.\n"
    "/.env\n"
    "/secrets/\n"
    "/..env.lock\n"
    "/..env.*.tmp\n"
    "/.docker-compose.yml.lock\n"
    "/.docker-compose.yml.*.tmp\n"
    "/..gitignore.lock\n"
    "/..gitignore.*.tmp\n"
    f"{GITIGNORE_MANAGED_END}\n"
)

GITHUB_APP_PRIVATE_KEY_FILE_NAME = "github-app-private-key.pem"

_PRIVATE_KEY_BOUNDARIES = (
    (
        b"-----BEGIN PRIVATE KEY-----",
        b"-----END PRIVATE KEY-----",
    ),
    (
        b"-----BEGIN RSA PRIVATE KEY-----",
        b"-----END RSA PRIVATE KEY-----",
    ),
    (
        b"-----BEGIN EC PRIVATE KEY-----",
        b"-----END EC PRIVATE KEY-----",
    ),
)


class SelfHostProtectionError(RuntimeError):
    """A self-host bundle could not be protected safely."""


def reconcile_gitignore(path: Path) -> bool:
    """Put the canonical managed block last, preserving operator content."""
    existing, mode = _read_regular_text_without_symlinks(path)

    merged = _merge_gitignore(existing)
    if merged == existing:
        return False
    atomic_replace_bytes(path, merged.encode("utf-8"), mode=mode)
    return True


def assert_sensitive_paths_untracked(target: Path) -> None:
    """Refuse when Git already tracks a bundle's config or secret files."""
    tracked = _tracked_sensitive_paths(target)
    if not tracked:
        return
    listing = ", ".join(tracked)
    raise SelfHostProtectionError(
        "Git already tracks sensitive self-host bundle files "
        f"({listing}). Ignore rules do not untrack files. Remove these paths "
        "from the Git index, rotate any credentials that entered history, "
        "then retry; no sensitive bundle file was written"
    )


def assert_bundle_path_safe(target: Path) -> None:
    """Refuse lexical worktree paths that traverse a symlink component."""
    selected = _absolute_without_symlink_resolution(target)
    repo_root = _lexical_git_root(selected)
    if repo_root is None:
        return
    try:
        relative_target = selected.relative_to(repo_root)
    except ValueError:
        raise SelfHostProtectionError(
            "self-host bundle path resolves outside its lexical Git worktree; "
            "choose a real directory instead of a symlinked path"
        ) from None
    cursor = repo_root
    for component in relative_target.parts:
        cursor /= component
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise SelfHostProtectionError(
                f"could not inspect self-host bundle path {cursor}: {exc}"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise SelfHostProtectionError(
                "self-host bundle path traverses a Git-worktree symlink "
                f"({cursor}); refusing to rely on lexical ignore rules for "
                "writes through an external directory"
            )


def install_github_app_private_key(
    *,
    secrets_dir: Path,
    source: Path,
) -> Path:
    """Validate and atomically publish a GitHub App private key as ``0600``."""
    selected_source = source.expanduser()
    try:
        secure_layout.prepare_bundle_layout(
            secrets_dir.parent,
            create=False,
        )
    except secure_layout.SecureLayoutError as exc:
        raise SelfHostProtectionError(str(exc)) from exc
    payload = _read_private_key_source(selected_source)
    _validate_private_key(payload)

    return atomic_replace_bytes(
        secrets_dir / GITHUB_APP_PRIVATE_KEY_FILE_NAME,
        payload,
        mode=0o600,
    )


def atomic_replace_bytes(target: Path, payload: bytes, *, mode: int) -> Path:
    """Converge ``target`` through the shared crash-recoverable writer."""
    try:
        return atomic_file.atomic_replace_bytes(target, payload, mode=mode)
    except atomic_file.AtomicFileError as exc:
        raise SelfHostProtectionError(str(exc)) from exc


def _merge_gitignore(existing: str) -> str:
    lines = existing.splitlines(keepends=True)
    begin_indexes = _marker_indexes(lines, GITIGNORE_MANAGED_BEGIN)
    end_indexes = _marker_indexes(lines, GITIGNORE_MANAGED_END)
    if not begin_indexes and not end_indexes:
        operator_text = existing
    elif (
        len(begin_indexes) == 1
        and len(end_indexes) == 1
        and begin_indexes[0] < end_indexes[0]
    ):
        operator_text = "".join(lines[: begin_indexes[0]] + lines[end_indexes[0] + 1 :])
    else:
        raise SelfHostProtectionError(
            "the Yoke-managed self-host block in .gitignore has missing, "
            "duplicate, or out-of-order markers; repair the markers before "
            "retrying so operator-authored rules are not overwritten"
        )

    if not operator_text:
        return GITIGNORE_MANAGED_BLOCK
    if operator_text.endswith("\n\n"):
        separator = ""
    elif operator_text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    return operator_text + separator + GITIGNORE_MANAGED_BLOCK


def _marker_indexes(lines: Iterable[str], marker: str) -> list[int]:
    return [index for index, line in enumerate(lines) if line.rstrip("\r\n") == marker]


def _tracked_sensitive_paths(target: Path) -> tuple[str, ...]:
    selected = _absolute_without_symlink_resolution(target)
    repo_root = _lexical_git_root(selected)
    if repo_root is None:
        return ()
    try:
        relative_target = selected.relative_to(repo_root)
    except ValueError:
        raise SelfHostProtectionError(
            "self-host bundle path is outside its lexical Git worktree"
        ) from None
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "--literal-pathspecs",
            "ls-files",
            "-z",
            "--",
            str(relative_target / ".env"),
            str(relative_target / "secrets"),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = os.fsdecode(result.stderr).strip() or "unknown git error"
        raise SelfHostProtectionError(
            f"could not verify self-host Git tracking state: {detail}"
        )
    return tuple(
        sorted(os.fsdecode(entry) for entry in result.stdout.split(b"\0") if entry)
    )


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _lexical_git_root(selected: Path) -> Path | None:
    for anchor in (selected, *selected.parents):
        try:
            result = subprocess.run(
                ["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None
        if result.returncode != 0:
            continue
        root = Path(os.fsdecode(result.stdout).strip())
        try:
            selected.relative_to(root)
        except ValueError:
            continue
        return root
    return None


def _read_private_key_source(path: Path) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or not hasattr(os, "geteuid"):
        raise SelfHostProtectionError(
            "platform cannot safely open the GitHub App private-key source"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
        ):
            raise SelfHostProtectionError(
                "GitHub App private-key source must be a current-owner, "
                f"single-link regular file: {path}"
            )
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise SelfHostProtectionError(
                "GitHub App private-key source must not be group/world "
                f"accessible: {path}; run `chmod 600 {path}` and retry"
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    except SelfHostProtectionError:
        raise
    except OSError as exc:
        raise SelfHostProtectionError(
            "could not safely open GitHub App private-key source "
            f"{path}: {exc}; use a real owner-only file and run `chmod 600 "
            f"{path}` before retrying"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_private_key(raw_payload: bytes) -> None:
    payload = raw_payload.strip()
    for begin, end in _PRIVATE_KEY_BOUNDARIES:
        if payload.startswith(begin) and payload.endswith(end):
            body = payload[len(begin) : -len(end)].strip()
            if body:
                return
    raise SelfHostProtectionError(
        "GitHub App private-key source is empty or is not an unencrypted "
        "PEM private key"
    )


def _read_regular_text_without_symlinks(path: Path) -> tuple[str, int]:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        return "", 0o644
    except OSError as exc:
        raise SelfHostProtectionError(
            f"could not safely read operator gitignore {path}: {exc}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SelfHostProtectionError(
                f"operator gitignore must be a regular file, not a symlink: {path}"
            )
        mode = stat.S_IMODE(info.st_mode)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            return stream.read(), mode
    except UnicodeDecodeError as exc:
        raise SelfHostProtectionError(
            f"operator gitignore is not UTF-8 text: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "GITHUB_APP_PRIVATE_KEY_FILE_NAME",
    "GITIGNORE_MANAGED_BEGIN",
    "GITIGNORE_MANAGED_BLOCK",
    "GITIGNORE_MANAGED_END",
    "SelfHostProtectionError",
    "assert_bundle_path_safe",
    "assert_sensitive_paths_untracked",
    "atomic_replace_bytes",
    "install_github_app_private_key",
    "reconcile_gitignore",
]
