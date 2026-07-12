"""Exec Git after changing into one inherited, already-validated directory."""

from __future__ import annotations

import os
import stat
import sys


def main(argv: list[str] | None = None) -> int:
    selected = list(sys.argv[1:] if argv is None else argv)
    if (
        len(selected) < 3
        or not selected[0].isdigit()
        or selected[1] != "--"
        or selected[2] != "git"
    ):
        return 126
    descriptor = int(selected[0])
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            return 126
        os.fchdir(descriptor)
        os.execvp("git", selected[2:])
    except OSError:
        return 126
    return 126


if __name__ == "__main__":  # pragma: no cover - process is replaced by Git
    raise SystemExit(main())
