"""Tool-shaped adapter for restoring a universe into a fresh self-host DB."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Callable, Dict, List, Tuple

from yoke_contracts.self_host_bootstrap import (
    IMPORT_UNIVERSE_ARG,
    RECOVER_IMPORT_CREDENTIAL_ARG,
)
from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.self_host import bundle


AdapterFn = Callable[[List[str]], int]

IMPORT_USAGE = "yoke self-host import ARCHIVE [--dir D] [--json]"
_RECOVERY_COMMAND = f"docker compose run --rm core {RECOVER_IMPORT_CREDENTIAL_ARG}"
_CORE_IMPORT_COMMAND = (IMPORT_UNIVERSE_ARG,)
_SUBPROCESS_RUN = subprocess.run


class SelfHostImportError(RuntimeError):
    """The local compose import orchestration failed safely."""


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _safe_diagnostic(value: bytes | str | None) -> str:
    text = _decode(value).strip()
    if not text:
        return ""
    printable = "".join(
        character if character.isprintable() else " " for character in text
    )
    return printable[-4096:]


def _run_compose(
    directory: Path,
    args: tuple[str, ...],
    *,
    stdin: BinaryIO | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return _SUBPROCESS_RUN(
            ("docker", "compose", *args),
            cwd=directory,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SelfHostImportError(
            "docker compose is unavailable; install Docker with Compose and retry"
        ) from exc
    except OSError as exc:
        raise SelfHostImportError(f"docker compose could not start: {exc}") from exc


def _require_core_stopped(directory: Path) -> None:
    result = _run_compose(
        directory,
        ("ps", "--all", "--format", "json", "core"),
    )
    if result.returncode != 0:
        diagnostic = _safe_diagnostic(result.stderr)
        suffix = f": {diagnostic}" if diagnostic else ""
        raise SelfHostImportError(f"could not inspect the core service{suffix}")
    text = _decode(result.stdout).strip()
    if not text:
        states: set[str] = set()
    else:
        try:
            decoded = json.loads(text)
            rows = decoded if isinstance(decoded, list) else [decoded]
        except json.JSONDecodeError:
            try:
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            except json.JSONDecodeError as exc:
                raise SelfHostImportError(
                    "docker compose returned an unreadable core service state"
                ) from exc
        if not all(isinstance(row, dict) for row in rows):
            raise SelfHostImportError(
                "docker compose returned an invalid core service state"
            )
        states = {str(row.get("State") or "unknown").strip().lower() for row in rows}
    unsafe = states - {"created", "dead", "exited"}
    if unsafe:
        listing = ", ".join(sorted(unsafe))
        raise SelfHostImportError(
            f"the core service is not stopped (state: {listing}); stop it with "
            "`docker compose stop core` before importing into a fresh database"
        )


def _open_archive(path: Path) -> BinaryIO:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise SelfHostImportError(
            "this platform cannot safely open a universe archive without following links"
        )
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SelfHostImportError(
                f"the universe archive must be a regular file: {path}"
            )
        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise SelfHostImportError(
                "the universe archive must be a current-owner, single-link "
                f"regular file: {path}"
            )
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise SelfHostImportError(
                "the universe archive contains private control-plane data and "
                f"must be owner-only; run `chmod 600 {path}` and retry"
            )
        stream = os.fdopen(descriptor, "rb")
        descriptor = -1
        return stream
    except SelfHostImportError:
        raise
    except OSError as exc:
        raise SelfHostImportError(
            f"the universe archive could not be opened safely: {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_success(stdout: bytes | str | None) -> Dict[str, object]:
    text = _decode(stdout).strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SelfHostImportError(
            "the restore committed but its one-time credential result could not "
            f"be read. Mint a recovery credential with: {_RECOVERY_COMMAND}"
        ) from exc
    if not isinstance(payload, dict):
        raise SelfHostImportError(
            "the restore committed but returned an invalid credential result. "
            f"Mint a recovery credential with: {_RECOVERY_COMMAND}"
        )
    raw_token = payload.get("raw_token")
    if (
        payload.get("ok") is not True
        or not isinstance(raw_token, str)
        or not raw_token.startswith("yoke_v1_")
    ):
        raise SelfHostImportError(
            "the restore committed but returned no usable credential. "
            f"Mint a recovery credential with: {_RECOVERY_COMMAND}"
        )
    return payload


def _execute_import(directory: Path, archive: BinaryIO) -> Dict[str, object]:
    _require_core_stopped(directory)
    database = _run_compose(
        directory,
        ("up", "-d", "--wait", "--wait-timeout", "120", "db"),
    )
    if database.returncode != 0:
        diagnostic = _safe_diagnostic(database.stderr)
        suffix = f": {diagnostic}" if diagnostic else ""
        raise SelfHostImportError(
            f"the self-host database did not become healthy{suffix}"
        )
    _require_core_stopped(directory)
    result = _run_compose(
        directory,
        ("run", "--rm", "-T", "core", *_CORE_IMPORT_COMMAND),
        stdin=archive,
    )
    if result.returncode != 0:
        diagnostic = _safe_diagnostic(result.stderr)
        suffix = f": {diagnostic}" if diagnostic else ""
        raise SelfHostImportError(f"the universe import was refused or failed{suffix}")
    return _parse_success(result.stdout)


def _print_summary(payload: Dict[str, object], directory: Path) -> None:
    border = "=" * 64
    print(f"universe imported: {payload.get('org')}")
    print(f"revoked imported credentials: {payload.get('revoked_token_count')}")
    print(
        f"revoked imported browser sessions: {payload.get('revoked_web_session_count')}"
    )
    print(border)
    print("SELF-HOST ADMIN TOKEN — shown once, never stored, never reprinted")
    print("")
    print(f"    {payload.get('raw_token')}")
    print("")
    print("Save it now. Then start and connect to the restored server:")
    print(f"    cd {directory} && docker compose up -d core")
    print("    yoke connect <server-url>")
    print(border)


def self_host_import(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke self-host import",
        description=(
            "Restore a portable universe archive into the catalog-empty "
            "database of an existing self-host bundle. The core service must "
            "be stopped. Imported platform-held API tokens and browser "
            "sessions are revoked, and one fresh org-admin token is shown "
            "exactly once."
        ),
    )
    parser.add_argument("archive", help="Owner-only pg_dump custom-format archive.")
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help=f"Existing bundle directory (default: ./{bundle.DEFAULT_BUNDLE_DIR}).",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, IMPORT_USAGE)
    if parsed is None:
        return 2
    try:
        directory = bundle.validate_existing_bundle(directory=parsed.directory)
        with _open_archive(Path(parsed.archive).expanduser()) as archive:
            payload = _execute_import(directory, archive)
    except (bundle.SelfHostBundleError, SelfHostImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_summary(payload, directory)
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("self-host", "import"): self_host_import,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke self-host import": IMPORT_USAGE,
}


__all__ = [
    "IMPORT_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "SelfHostImportError",
    "self_host_import",
]
