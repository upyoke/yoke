"""Project-scoped scratch path helpers.

Yoke-owned transient paths use ``YOKE_SCRATCH_ROOT``,
``~/.yoke/config.json:temp_root``, or OS temp with project/session/run
segments; repo-local data dirs are never the default. Cross-process
coordination surfaces (hook markers, harness runtime cache) stay
project-stable — no session/run segments — so sibling hook processes of
one harness session resolve the same files.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from yoke_core.domain import machine_config
from yoke_core.domain import project_scratch_roots
from yoke_core.domain.project_scratch_roots import (
    ENV_KEY,
    ScratchRootResolutionError,
    global_scratch_root,
)
from yoke_core.domain.project_scratch_segments import (
    ScratchSessionIdentityError,
    require_resolved_session_segment,
    run_segment as _run_segment,
    safe_segment as _safe_segment,
    session_segment as _session_segment,
)

__all__ = [
    "ScratchRootResolutionError",
    "ScratchSessionIdentityError",
    "dispatch_inputs_dir",
    "ephemeral_payload",
    "global_scratch_root",
    "harness_runtime_cache_path",
    "hook_marker_path",
    "mint_watcher_capture_pair",
    "resolve_active_project",
    "scratch_root",
    "scratch_subdir",
    "storage_dir",
    "storage_path",
    "watcher_capture_path",
]


DEFAULT_PROJECT = "yoke"


def resolve_active_project(project: str | None = None) -> str:
    """Return explicit project, ``$YOKE_PROJECT``, checkout config, or yoke."""

    for value in (
        project,
        os.environ.get("YOKE_PROJECT"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    configured_id = machine_config.project_id(Path.cwd())
    if configured_id is not None:
        return str(configured_id)
    return DEFAULT_PROJECT


def scratch_root(
    project: str | None = None, *, session_segment: str | None = None,
) -> Path:
    """Return the writable project/session/run scratch root.

    ``session_segment`` lets a caller that has already resolved (and
    vetted) the session namespace supply it, instead of resolving ambient
    identity a second time.
    """

    active_project = resolve_active_project(project)
    root = (
        global_scratch_root()
        / _safe_segment(active_project)
        / "sessions"
        / (session_segment or _session_segment())
        / "runs"
        / _run_segment()
    )
    if project_scratch_roots.ensure_writable_dir(root):
        return root
    raise ScratchRootResolutionError(
        f"Unable to create writable scratch root at {root}. "
        f"Set {ENV_KEY} to a writable path."
    )


def dispatch_inputs_dir(
    project: str | None = None,
    item_id: int | str | None = None,
    session_id: str | None = None,
    attempt: int | str | None = None,
    *,
    create: bool = True,
) -> Path:
    """Return the dispatch-inputs directory.

    Optional ``item_id`` / ``session_id`` / ``attempt`` extend the path with a
    per-dispatch ``YOK-{N}/{session_id}/attempt-{n}`` subtree; all three must
    be supplied together. ``item_id`` is the bare internal ``items.id``
    (public ``PREFIX-N`` refs are resolved by callers before this point).
    """

    path = scratch_root(project) / "dispatch-inputs"
    per_dispatch = (item_id, session_id, attempt)
    supplied = sum(1 for value in per_dispatch if value is not None)
    if supplied not in (0, 3):
        raise ValueError(
            "dispatch_inputs_dir requires all three of "
            "item_id, session_id, attempt — or none"
        )
    if supplied == 3:
        path = path / f"YOK-{int(item_id)}" / _safe_segment(str(session_id)) / (
            f"attempt-{int(str(attempt))}"
        )
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def hook_marker_path(
    name: str, project: str | None = None, *, create_parent: bool = True
) -> Path:
    """Return a hook marker path under the project-stable ``hook-markers``.

    Hook markers coordinate fire-once state across harness hook processes
    (each hook event runs in a fresh process), so the path must be a stable
    function of *name* alone — never of the ambient session or ``pid-<n>``
    run segments, which differ per hook process and would defeat the dedup.
    """

    return _stable_rooted_path(
        project, "hook-markers", _safe_segment(name),
        create_parent=create_parent,
    )


def harness_runtime_cache_path(
    name: str, project: str | None = None, *, create_parent: bool = True
) -> Path:
    """Return a project-stable path under ``harness-runtime-cache``.

    The cache is written by one hook process (e.g. Codex SessionStart) and
    read by later ones (prompt-submit), so like hook markers it must not
    embed per-process session/run segments.
    """

    return _stable_rooted_path(
        project, "harness-runtime-cache", _safe_segment(name),
        create_parent=create_parent,
    )


def watcher_capture_path(
    command: str,
    stream: str,
    nonce: str | None = None,
    project: str | None = None,
    *,
    suffix: str = ".log",
    create_parent: bool = True,
) -> Path:
    """Return a watcher capture path sharing the given *nonce*.

    Raises :class:`ScratchSessionIdentityError` rather than minting a
    capture under the unknown-session placeholder inside a harness
    session, where that path is one the session-cwd guard then refuses.
    """

    safe_command = _safe_segment(command)
    safe_stream = _safe_segment(stream)
    safe_nonce = _safe_segment(nonce or uuid.uuid4().hex)
    filename = f"yoke-{safe_command}.{safe_stream}.{safe_nonce}{suffix}"
    root = scratch_root(project, session_segment=require_resolved_session_segment())
    path = root / "watcher-captures" / filename
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def mint_watcher_capture_pair(
    command: str, project: str | None = None
) -> tuple[Path, Path]:
    """Return ``(raw_capture, progress_capture)`` sharing one nonce."""

    nonce = uuid.uuid4().hex
    return (
        watcher_capture_path(command, "raw", nonce, project),
        watcher_capture_path(command, "progress", nonce, project),
    )


@contextmanager
def ephemeral_payload(
    prefix: str = "payload",
    suffix: str = "",
    project: str | None = None,
    *,
    delete: bool = True,
) -> Iterator[Path]:
    """Create a temporary payload file and optionally delete it on exit."""

    parent = scratch_root(project) / "payloads"
    parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f"{_safe_segment(prefix)}.",
        suffix=suffix,
        dir=parent,
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    try:
        yield path
    finally:
        if delete:
            path.unlink(missing_ok=True)


@contextmanager
def scratch_subdir(
    prefix: str = "scratch",
    project: str | None = None,
    *,
    delete: bool = True,
) -> Iterator[Path]:
    """Create a temporary scratch directory and optionally remove it on exit."""

    parent = scratch_root(project) / "scratch-dirs"
    parent.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=f"{_safe_segment(prefix)}.", dir=parent))
    try:
        yield path
    finally:
        if delete:
            shutil.rmtree(path, ignore_errors=True)


def storage_path(
    kind: str,
    *parts: str,
    project: str | None = None,
    create_parent: bool = True,
) -> Path:
    """Return a durable scratch-storage path under ``storage/<kind>``."""

    path_parts = [_safe_segment(kind), *[_safe_segment(p) for p in parts]]
    return _rooted_path(project, "storage", *path_parts,
                        create_parent=create_parent)


def storage_dir(
    kind: str,
    *parts: str,
    project: str | None = None,
    create: bool = True,
) -> Path:
    """Return a durable scratch-storage directory under ``storage/<kind>``."""

    path_parts = [_safe_segment(kind), *[_safe_segment(p) for p in parts]]
    path = scratch_root(project).joinpath("storage", *path_parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _rooted_path(
    project: str | None,
    *parts: str,
    create_parent: bool,
) -> Path:
    path = scratch_root(project).joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _stable_rooted_path(
    project: str | None,
    *parts: str,
    create_parent: bool,
) -> Path:
    """Resolve *parts* under the project root without session/run segments."""

    active_project = resolve_active_project(project)
    path = global_scratch_root().joinpath(_safe_segment(active_project), *parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path
