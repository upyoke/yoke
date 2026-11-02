"""Explain why convention detection selected no dependency install."""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path
from typing import Callable


def report_no_dependency_install(
    worktree_path: str,
    project_id: str | None,
    filenames: list[str],
    find_file: Callable[..., str | None],
) -> None:
    """Report detected files without changing installer selection or exit codes."""
    root = Path(worktree_path)
    found = [
        Path(path).relative_to(root).as_posix()
        for filename in [*filenames, "pyproject.toml"]
        if (path := find_file(worktree_path, filename, max_depth=3))
    ]
    if found:
        print(
            f"Dependency files detected: {', '.join(found)} — "
            "no convention install selected; skipping install",
            file=sys.stderr,
        )
        for relative in found:
            if Path(relative).name != "pyproject.toml":
                continue
            if (root / relative).with_name("uv.lock").is_file():
                continue  # Lane provisioning already explained its ownership.
            missing = "uv not on PATH; " if shutil.which("uv") is None else ""
            print(
                f"Skipping {relative}: {missing}uv provisioning requires uv.lock "
                "beside pyproject.toml; a bare pyproject.toml has no convention installer",
                file=sys.stderr,
            )
    else:
        print("No dependency files detected — skipping install", file=sys.stderr)
    project = shlex.quote(str(project_id)) if project_id else "<project>"
    print(
        "Register a project setup_command capability to install dependencies: "
        f"yoke projects capability-settings set --project {project} "
        "--cap-type setup_command --settings-json "
        "'{\"command\":\"<setup command>\"}' --new",
        file=sys.stderr,
    )
