"""Recognize configured and legacy scratch roots without selecting a project.

Classification reads the shared root candidate inventory. It neither chooses
a writer's project nor probes or creates directories at import time.
"""

from __future__ import annotations

import tempfile
from typing import Iterable

from yoke_contracts.machine_config.scratch_roots import scratch_root_candidates

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

    Order is deterministic: configured global scratch candidates first, then the legacy tempdir
    prefixes that retain live writers. Duplicates are filtered.
    """

    roots = list(
        dict.fromkeys(str(path).rstrip("/") for path in scratch_root_candidates())
    )

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
