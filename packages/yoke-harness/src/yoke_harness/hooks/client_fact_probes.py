"""Client-machine probes behind the named hook facts.

Each probe answers one question only the machine running the harness can
answer and returns the fact envelope from
:mod:`yoke_contracts.hook_runner.client_facts`, or ``{}`` when the question
does not apply here (no Yoke source checkout, no git repository).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from typing import Mapping

from yoke_contracts.hook_runner import client_facts as cf
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.scratch_roots import scratch_path_roots
from yoke_contracts.watch_capture import capture_state

from yoke_harness.hooks.local_policy_common import (
    command_from_payload,
    cwd_from_payload,
)

_GIT_TIMEOUT_S = 5
#: A command naming more captures than this is not a capture peek.
_MAX_CAPTURE_FILES = 16


def capture_files_fact(payload: Mapping[str, object]) -> dict:
    """Report this machine's scratch roots and each capture the command names."""
    roots = scratch_path_roots()
    alternation = "|".join(re.escape(root) for root in roots)
    files: dict[str, dict] = {}
    command = command_from_payload(dict(payload))
    if command and alternation:
        for path in re.findall(rf"(?:{alternation})/[\w./-]+", command):
            if path not in files and len(files) < _MAX_CAPTURE_FILES:
                files[path] = capture_state(path)
    return cf.client_fact(cf.CAPTURE_FILES_KEY, {"roots": roots, "files": files})


def _git(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def main_head_fact(payload: Mapping[str, object]) -> dict:
    """Report the newest ``main`` commits of the checkout the session runs in."""
    log = _git(
        cwd_from_payload(dict(payload)),
        "log",
        "main",
        f"-{cf.MAIN_HEAD_HISTORY}",
        "--format=%H%x1f%s",
    )
    commits = [
        line.split("\x1f", 1) for line in (log or "").splitlines() if "\x1f" in line
    ]
    return cf.client_fact(cf.MAIN_HEAD_KEY, {"commits": commits}) if commits else {}


def yoke_source_root() -> str:
    """Return the Yoke source checkout this machine's engine code runs from.

    An installed wheel lives in site-packages with no git checkout above it,
    so a non-source install has none (``""``). A lane worktree answers its
    main checkout, the control plane a lane's own writes never target.
    """
    spec = importlib.util.find_spec("yoke_core")
    origin = spec.origin if spec is not None else None
    if not origin:
        return ""
    start = Path(origin).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return str(main_checkout(candidate))
    return ""


def yoke_source_root_fact() -> dict:
    """Report :func:`yoke_source_root` as a client fact, when there is one."""
    root = yoke_source_root()
    return cf.client_fact(cf.SOURCE_ROOT_KEY, root) if root else {}


__all__ = [
    "capture_files_fact",
    "main_head_fact",
    "yoke_source_root",
    "yoke_source_root_fact",
]
