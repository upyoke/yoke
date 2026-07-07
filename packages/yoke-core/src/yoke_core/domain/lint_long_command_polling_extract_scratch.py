"""Helper-resolved scratch-path recognition for the polling lint.

The polling lint needs to know which paths are Yoke-owned ephemeral
scratch — the helper-resolved roots under ``project_scratch_dir`` and
the legacy ``tempfile.gettempdir()`` prefixes that still see live
writers. Centralizing the classification here keeps the parent extract
module under the 350-line cap (AD-8 defensive sibling extraction) and
gives downstream callers (denial messages, audit emission) one place
to ask "is this a Yoke scratch path?".

Functions here are pure: they read from environment + the scratch
helper at call time and have no filesystem side effects.
"""

from __future__ import annotations

import os
import tempfile
from typing import Iterable

from yoke_core.domain import project_scratch_dir

__all__ = [
    "is_helper_resolved_scratch_path",
    "scratch_path_roots",
]


def _legacy_tmp_roots() -> Iterable[str]:
    """Return the tempdir-prefixed roots the polling lint already accepts.

    Mirrors the prefix discovery in
    :func:`lint_long_command_polling_extract._temp_dir_prefixes` so
    callers receive every shape the regex matchers tolerate.
    """

    yield "/tmp"
    yield "/private/tmp"
    sys_tmp = tempfile.gettempdir().rstrip("/")
    if sys_tmp and sys_tmp not in {"/tmp", "/private/tmp"}:
        yield sys_tmp
        if sys_tmp.startswith("/var/"):
            yield "/private" + sys_tmp


def scratch_path_roots() -> list[str]:
    """Return absolute roots a Yoke scratch artefact may live under.

    Order is deterministic: helper-resolved scratch root first (the
    canonical write target for new callers), then the legacy tempdir
    prefixes that retain live writers. Duplicates are filtered.
    """

    roots: list[str] = []

    try:
        helper_root = str(project_scratch_dir.scratch_root()).rstrip("/")
    except project_scratch_dir.ScratchRootResolutionError:
        helper_root = ""
    if helper_root and helper_root not in roots:
        roots.append(helper_root)

    override_env = os.environ.get(project_scratch_dir.ENV_KEY, "").strip()
    if override_env:
        normalized = override_env.rstrip("/")
        if normalized and normalized not in roots:
            roots.append(normalized)

    for legacy in _legacy_tmp_roots():
        normalized = legacy.rstrip("/")
        if normalized and normalized not in roots:
            roots.append(normalized)

    return roots


def is_helper_resolved_scratch_path(path: str) -> bool:
    """Return ``True`` when *path* falls under a Yoke scratch root.

    Recognises every prefix returned by :func:`scratch_path_roots` —
    the helper-resolved root, the explicit env override (when set),
    plus the legacy tempdir prefixes (``/tmp``, ``/private/tmp``,
    ``tempfile.gettempdir()`` and its ``/private`` canonical pair on
    macOS). Returns ``False`` for the empty string and for paths that
    do not start with one of the recognised roots.
    """

    if not path:
        return False
    candidate = path.rstrip("/") or path
    for root in scratch_path_roots():
        if candidate == root or candidate.startswith(root + "/"):
            return True
    return False
