"""Name a shell's missing working directory without choosing another folder."""

import json
import os

MISSING_MESSAGE = (
    "working_directory_missing: this shell's folder no longer exists "
    "(a merged lane folder is removed after it lands); "
    "cd to the project checkout and retry"
)


class WorkingDirectoryMissing(RuntimeError):
    """The shell remains in a folder that has been removed."""


def current_directory() -> str:
    """Return the process cwd, or explain how to recover a removed folder."""
    try:
        return os.getcwd()
    except FileNotFoundError:
        raise WorkingDirectoryMissing(MISSING_MESSAGE) from None


def require_payload_directory(raw_payload: str) -> None:
    """Refuse a hook payload whose absolute session folder has been removed.

    A harness may start its hook child in a surviving folder while the
    session's own folder (the payload ``cwd``) is gone. A missing, relative
    or malformed ``cwd`` says nothing about the session folder and passes.
    """
    try:
        payload = json.loads(raw_payload)
    except (ValueError, TypeError):
        return
    value = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(value, str) and os.path.isabs(value) and not os.path.isdir(value):
        raise WorkingDirectoryMissing(MISSING_MESSAGE)
