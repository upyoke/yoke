"""Private atomic output handling for portable universe archives."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from yoke_contracts import platform_file_sync
from yoke_contracts.owner_private_path import (
    create_owner_private_temporary,
    is_owner_private_file,
)

_WINDOWS = os.name == "nt"


class PrivateArchiveOutputError(RuntimeError):
    """An archive destination cannot be replaced without weakening safety."""


def _validate_existing_destination(destination: Path) -> None:
    try:
        info = destination.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PrivateArchiveOutputError(
            f"the universe archive destination cannot be inspected: {destination}"
        ) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or (not is_owner_private_file(destination) if _WINDOWS
            else info.st_uid != os.geteuid())
        or info.st_nlink != 1
    ):
        raise PrivateArchiveOutputError(
            "the universe archive destination must be a current-owner, "
            f"single-link regular file: {destination}"
        )


@dataclass
class PrivateArchiveOutput:
    """One private temporary stream committed atomically to its destination."""

    destination: Path
    temporary: Path
    stream: BinaryIO
    committed: bool = False

    def __enter__(self) -> BinaryIO:
        return self.stream

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        try:
            if exc_type is None:
                self.stream.flush()
                os.fsync(self.stream.fileno())
        finally:
            self.stream.close()

    def commit(self) -> None:
        """Replace a still-safe destination with the completed private file."""
        if not self.stream.closed:
            raise PrivateArchiveOutputError(
                "the universe archive stream is still open during commit"
            )
        _validate_existing_destination(self.destination)
        try:
            os.replace(self.temporary, self.destination)
            platform_file_sync.sync_directory(self.destination.parent)
        except OSError as exc:
            raise PrivateArchiveOutputError(
                f"the universe archive could not be committed: {self.destination}"
            ) from exc
        self.committed = True

    def cleanup(self) -> None:
        """Close and remove only the private temporary artifact."""
        if not self.stream.closed:
            self.stream.close()
        if not self.committed:
            self.temporary.unlink(missing_ok=True)


def prepare_private_archive_output(destination: Path) -> PrivateArchiveOutput:
    """Validate the destination and create a private sibling temporary file."""
    _validate_existing_destination(destination)
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, temporary = create_owner_private_temporary(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            directory=destination.parent,
        )
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        return PrivateArchiveOutput(destination, temporary, stream)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise PrivateArchiveOutputError(
            f"the private universe archive output could not be created: {destination}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "PrivateArchiveOutput",
    "PrivateArchiveOutputError",
    "prepare_private_archive_output",
]
