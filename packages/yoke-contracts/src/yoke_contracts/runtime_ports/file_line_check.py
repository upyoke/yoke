"""Runtime interface for file line check."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class FileLineCheck(Protocol):
    """Operations and values supplied by the executing adapter."""

    ARCHIVE_EXCEPTIONS: Any
    ChangedFile: type[Any]
    CheckVerdict: type[Any]
    Classification: type[Any]
    FileEntry: type[Any]
    LIMIT: Any
    TEMPORARY_EXCEPTIONS: Any
    changed_files_check: Callable[..., Any]
    classify_path: Callable[..., Any]
    inventory: Callable[..., Any]
    resolved_policy: Callable[..., Any]


def get_file_line_check() -> FileLineCheck:
    return cast(FileLineCheck, load_port("file_line_check", FileLineCheck))
