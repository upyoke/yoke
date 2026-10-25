"""Stream one Test Machine file to a local path over a host's SSH connection.

Each host adapter supplies the argv of a reader script for its own shell. The
script checks the target, then writes the file as base64 on stdout. Base64
keeps the bytes intact through every transport, including Windows OpenSSH and
PowerShell into WSL. This module decodes the stream in fixed-size chunks
straight into the destination, so no file is ever held whole in memory.

A reader script refuses with one of the exit codes below. Each code maps to a
named refusal with its recovery.
"""

from __future__ import annotations

import base64
import binascii
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Sequence

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_contracts.refusal_recovery import compose_refusal

COPY_TIMEOUT_SECONDS = 600
_CHUNK_BYTES = 64 * 1024
_BASE64_WHITESPACE = b" \t\r\n"

NOT_ABSOLUTE_EXIT = 64
NOT_REGULAR_EXIT = 65
MISSING_EXIT = 66
TOO_LARGE_EXIT = 67
REFUSED_ROOT_EXIT = 68
UNREADABLE_EXIT = 69

# Reader scripts take TARGET, MAX_BYTES and REFUSED_ROOT as $1, $2 and $3.
# Both resolve symlinks before the refused-root check, so no link can reach
# into that directory.
ZSH_READER = (
    'target="$1"; max="$2"; [[ "$target" == /* ]] || exit 64; '
    '[[ -e "$target" ]] || exit 66; '
    'resolved="${target:A}"; root="${3:A}"; '
    '[[ "$resolved" == "$root" || "$resolved" == "$root"/* ]] && exit 68; '
    '[[ -f "$resolved" ]] || exit 65; [[ -r "$resolved" ]] || exit 69; '
    'size=$(/usr/bin/wc -c < "$resolved") || exit 69; '
    "(( size <= max )) || exit 67; "
    'exec /usr/bin/base64 < "$resolved"'
)
BASH_READER = (
    'target="$1"; max="$2"; [[ "$target" == /* ]] || exit 64; '
    '[[ -e "$target" ]] || exit 66; '
    'resolved=$(realpath -e -- "$target") || exit 66; '
    'root=$(realpath -m -- "$3") || exit 69; '
    '[[ "$resolved" == "$root" || "$resolved" == "$root"/* ]] && exit 68; '
    '[[ -f "$resolved" ]] || exit 65; [[ -r "$resolved" ]] || exit 69; '
    'size=$(wc -c < "$resolved") || exit 69; '
    "(( size <= max )) || exit 67; "
    'exec base64 < "$resolved"'
)


class HostCopyRefused(RuntimeError):
    """A copy that wrote nothing, with its named reason and recovery."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _refusal(code: str, reason: str, recovery: str) -> HostCopyRefused:
    return HostCopyRefused(code, compose_refusal(reason, recovery=recovery))


def too_large(path: str, max_bytes: int) -> HostCopyRefused:
    return _refusal(
        "host_copy_file_too_large",
        f"{path} is larger than the {max_bytes}-byte QA artifact limit",
        "Copy a smaller file: crop or compress it on the Test Machine with "
        "host-command, then copy the result",
    )


def exit_refusal(
    returncode: int, path: str, max_bytes: int, refused_root: str, stderr: str
) -> HostCopyRefused:
    """Name the refusal a reader script's exit code stands for."""
    if returncode == NOT_ABSOLUTE_EXIT:
        return _refusal(
            "host_copy_path_not_absolute",
            f"--from {path!r} is not an absolute Test Machine path",
            "Pass the file's absolute path on the Test Machine",
        )
    if returncode == MISSING_EXIT:
        return _refusal(
            "host_copy_file_missing",
            f"{path} does not exist on the Test Machine",
            "List the directory with host-command -- /bin/ls -la DIR and pass "
            "the file's exact path",
        )
    if returncode == NOT_REGULAR_EXIT:
        return _refusal(
            "host_copy_not_a_file",
            f"{path} is not a regular file on the Test Machine",
            "Copy one file at a time; archive a directory with host-command "
            "first, then copy the archive",
        )
    if returncode == TOO_LARGE_EXIT:
        return too_large(path, max_bytes)
    if returncode == REFUSED_ROOT_EXIT:
        return _refusal(
            "host_copy_path_in_mission_scratch",
            f"{path} is inside {refused_root}, which holds staged secrets",
            "Copy evidence from outside the mission scratch directory; never "
            "attach staged secret files",
        )
    if returncode == UNREADABLE_EXIT:
        return _refusal(
            "host_copy_file_unreadable",
            f"the Test Machine user cannot read {path}",
            "Make the file readable with host-command, or copy a readable copy of it",
        )
    detail = f" ({stderr})" if stderr else ""
    return _refusal(
        "host_copy_transfer_failed",
        f"the copy of {path} stopped with exit {returncode}{detail}",
        "Check the host with `yoke test-machine verify`, then retry the copy",
    )


def _decode_into(stream, sink, *, path: str, max_bytes: int) -> int:
    pending = b""
    written = 0
    while chunk := stream.read(_CHUNK_BYTES):
        pending += chunk.translate(None, _BASE64_WHITESPACE)
        usable = len(pending) - len(pending) % 4
        decoded = base64.b64decode(pending[:usable], validate=True)
        pending = pending[usable:]
        written += len(decoded)
        if written > max_bytes:
            raise too_large(path, max_bytes)
        sink.write(decoded)
    if pending:
        raise binascii.Error("truncated base64 stream")
    return written


def stream_remote_file(
    argv: Sequence[str],
    destination: Path,
    *,
    path: str,
    max_bytes: int,
    refused_root: str,
    secret_values: tuple[str, ...] = (),
) -> int:
    """Run a reader argv and write the decoded bytes to ``destination``.

    The bytes land in a temporary file beside the destination, which replaces
    the destination only after the whole file arrived. Returns the byte count.
    """
    destination = Path(destination)
    if not destination.parent.is_dir():
        raise _refusal(
            "host_copy_destination_unavailable",
            f"--to {destination}: the directory {destination.parent} does not exist",
            "Create the local directory first, or pass a path in an existing one",
        )
    if destination.is_dir():
        raise _refusal(
            "host_copy_destination_unavailable",
            f"--to {destination} is a directory",
            "Pass a file path, such as DIR/screenshot.png",
        )
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".partial"
    )
    try:
        with tempfile.TemporaryFile() as stderr, os.fdopen(descriptor, "wb") as sink:
            try:
                process = subprocess.Popen(
                    list(argv),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                )
            except OSError as exc:
                raise _refusal(
                    "host_copy_transfer_failed",
                    f"ssh could not start ({type(exc).__name__})",
                    "Install OpenSSH on this machine, then retry the copy",
                ) from exc
            timer = threading.Timer(COPY_TIMEOUT_SECONDS, process.kill)
            timer.start()
            try:
                written = _decode_into(
                    process.stdout, sink, path=path, max_bytes=max_bytes
                )
            except binascii.Error:
                written = None
            except BaseException:
                process.kill()
                raise
            finally:
                timer.cancel()
                returncode = process.wait()
            stderr.seek(0)
            diagnostic = bounded_machine_qa_diagnostic(
                stderr.read().decode("utf-8", errors="backslashreplace"),
                secret_values,
            )
        if returncode == 0 and written is not None:
            os.replace(temporary, destination)
            return written
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if returncode < 0:
        raise _refusal(
            "host_copy_timed_out",
            f"the copy of {path} did not finish within {COPY_TIMEOUT_SECONDS}s",
            "Check the host with `yoke test-machine verify`, then retry the copy",
        )
    if returncode == 0:
        raise _refusal(
            "host_copy_transfer_failed",
            f"the copy of {path} arrived as a damaged stream",
            "Retry the copy; if it fails again, check the host with "
            "`yoke test-machine verify`",
        )
    raise exit_refusal(returncode, path, max_bytes, refused_root, diagnostic)


__all__ = [
    "BASH_READER",
    "COPY_TIMEOUT_SECONDS",
    "HostCopyRefused",
    "ZSH_READER",
    "exit_refusal",
    "stream_remote_file",
]
