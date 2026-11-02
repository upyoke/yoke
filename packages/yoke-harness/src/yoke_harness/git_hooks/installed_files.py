"""Keep staged installer-owned files on proven release bytes."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import subprocess

from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.released_bundle_files import ReleasedBundleFiles
from yoke_contracts import terminal_detached_process
from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_contracts.project_contract.file_line_policy import GENERATED_PATH_GLOBS


def _git(root: Path, *args: str) -> bytes:
    result = terminal_detached_process.run(
        ["git", "-C", str(root), *args], capture_output=True, timeout=10,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def check(root: Path) -> str | None:
    """Inspect index bytes, independently of manifests and working-tree edits."""
    if is_yoke_source_checkout(root):
        return None
    try:
        paths = _git(
            root, "diff", "--cached", "--name-only", "--no-renames",
            "--diff-filter=ACMRT", "-z",
        ).decode("utf-8").split("\0")
        releases = ReleasedBundleFiles()
        refused = []
        for rel in paths:
            if not any(fnmatchcase(rel, glob) for glob in GENERATED_PATH_GLOBS):
                continue
            content = _git(root, "show", f":{rel}").decode("utf-8")
            if not releases.proves(rel, content):
                refused.append(rel)
        if refused:
            return (
                "ERROR: installer_owned_file_modified: commit refused.\n"
                + "".join(f"  {rel}\n" for rel in refused)
                + "This file belongs to Yoke's installer; send the change to Yoke "
                "with `yoke feedback --to yoke`, or put it in a project-owned file.\n"
                "Restore release bytes with `yoke project refresh`, stage them, "
                "then commit again.\n"
            )
    except ProjectInstallError as exc:
        return f"ERROR: {exc}\n"
    except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
        return (
            f"ERROR: installer_owned_file_check_failed: {exc}\n"
            "Repair the Git index and UTF-8 staged files, then commit again.\n"
        )
    return None
