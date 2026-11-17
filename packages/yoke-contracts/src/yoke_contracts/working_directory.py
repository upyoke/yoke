"""Name a shell's missing working directory without choosing another folder."""

import os


class WorkingDirectoryMissing(RuntimeError):
    """The shell remains in a folder that has been removed."""


def current_directory() -> str:
    """Return the process cwd, or explain how to recover a removed folder."""
    try:
        return os.getcwd()
    except FileNotFoundError:
        raise WorkingDirectoryMissing(
            "working_directory_missing: this shell's folder no longer exists "
            "(a merged lane folder is removed after it lands); "
            "cd to the project checkout and retry"
        ) from None
