"""Install-time preflight: warn when the commit gate would be shadowed.

``yoke project install`` writes the pre-commit file-line gate into
``<root>/.git/hooks``. Two ambient conditions silently defeat it even after a
clean install:

* a ``core.hooksPath`` git setting that points git at a hooks directory other
  than ``<root>/.git/hooks`` — git then runs that directory's hooks and never
  the freshly written Yoke shim; and
* a missing ``yoke`` launcher on PATH — the shims ``exec yoke ...``, so a
  hooked commit cannot run the gate at all without it.

Neither is fatal to the install itself, so both surface as loud report
warnings the install flow folds into its returned ``warnings`` list.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


def _core_hooks_path(root: Path) -> Optional[str]:
    """Return the configured ``core.hooksPath`` for ``root``, or None."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0 and completed.stdout.strip():
        return completed.stdout.strip()
    return None


def collect_hooks_path_warnings(root: Path) -> List[str]:
    """Return warnings for conditions that would shadow the commit gate."""
    warnings: List[str] = []

    default_hooks_dir = root / ".git" / "hooks"
    core_hooks_path = _core_hooks_path(root)
    if core_hooks_path:
        candidate = Path(core_hooks_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.resolve() != default_hooks_dir.resolve():
            warnings.append(
                f"core.hooksPath is set to {core_hooks_path}; the Yoke commit "
                "gate in .git/hooks will be shadowed — unset it (git config "
                "--unset core.hooksPath) or point it at .git/hooks."
            )

    if shutil.which("yoke") is None:
        warnings.append(
            "the `yoke` launcher is not on PATH; the installed git hook shims "
            "`exec yoke ...` and cannot run the commit gate until `yoke` is on "
            "PATH — repair the machine CLI with the public installer."
        )

    return warnings


__all__ = ["collect_hooks_path_warnings"]
