"""Project-scoped scratch path helpers.

Yoke-owned transient paths use ``YOKE_SCRATCH_ROOT``,
``~/.yoke/config.json:temp_root``, or OS temp with project/session/run
segments; repo-local data dirs are never the default.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from yoke_core.domain import machine_config

__all__ = [
    "ScratchRootResolutionError",
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


ENV_KEY = "YOKE_SCRATCH_ROOT"
DEFAULT_PROJECT = "yoke"
RUN_ENV_KEYS = ("YOKE_RUN_ID", "YOKE_EXECUTION_ID", "GITHUB_RUN_ID")
DEFAULT_SESSION_SEGMENT = "session-unknown"


class ScratchRootResolutionError(RuntimeError):
    """Raised when no writable scratch root can be resolved."""


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


def global_scratch_root() -> Path:
    """Return the writable scratch root shared across ALL projects."""

    override = _override_root()
    if override is not None:
        resolved = _absolute_root(override)
        if _ensure_writable_dir(resolved):
            return resolved
        warnings.warn(
            f"scratch root {resolved} is not writable; falling back to "
            f"{_fallback_base()}",
            RuntimeWarning,
            stacklevel=2,
        )

    fallback = _fallback_base()
    if _ensure_writable_dir(fallback):
        return fallback
    raise ScratchRootResolutionError(
        f"Unable to create writable scratch root at {fallback}. "
        f"Set {ENV_KEY} to a writable path."
    )


def scratch_root(project: str | None = None) -> Path:
    """Return the writable project/session/run scratch root."""

    active_project = resolve_active_project(project)
    root = (
        global_scratch_root()
        / _safe_segment(active_project)
        / "sessions"
        / _session_segment()
        / "runs"
        / _run_segment()
    )
    if _ensure_writable_dir(root):
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
    be supplied together.
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
        bare_id = _strip_sun_prefix(item_id)
        path = path / f"YOK-{bare_id}" / _safe_segment(str(session_id)) / (
            f"attempt-{int(str(attempt))}"
        )
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _strip_sun_prefix(item_id: int | str | None) -> int:
    if isinstance(item_id, int):
        return item_id
    text = str(item_id).strip()
    if text.upper().startswith("YOK-"):
        text = text[4:]
    return int(text)


def hook_marker_path(
    name: str, project: str | None = None, *, create_parent: bool = True
) -> Path:
    """Return a hook marker path under ``hook-markers``."""

    return _rooted_path(
        project, "hook-markers", _safe_segment(name),
        create_parent=create_parent,
    )


def harness_runtime_cache_path(
    name: str, project: str | None = None, *, create_parent: bool = True
) -> Path:
    """Return a harness runtime cache path under ``harness-runtime-cache``."""

    return _rooted_path(
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
    """Return a watcher capture path sharing the given *nonce*."""

    safe_command = _safe_segment(command)
    safe_stream = _safe_segment(stream)
    safe_nonce = _safe_segment(nonce or uuid.uuid4().hex)
    filename = f"yoke-{safe_command}.{safe_stream}.{safe_nonce}{suffix}"
    return _rooted_path(
        project, "watcher-captures", filename, create_parent=create_parent
    )


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


def _override_root() -> str | None:
    env_value = os.environ.get(ENV_KEY, "").strip()
    if env_value:
        return env_value
    return machine_config.temp_root()


def _fallback_base() -> Path:
    base = Path(tempfile.gettempdir())
    if str(base).startswith("/var/folders/") and Path("/tmp").is_dir():
        base = Path("/tmp")
    return base / "yoke-scratch"


def _absolute_root(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return machine_config.yoke_home() / path


def _first_env(keys: tuple[str, ...]) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def _session_segment() -> str:
    # Ambient identity (env chain, then anchor registry): desktop sessions
    # carry no env stamp, so env-only resolution namespaced everything
    # under ``session-unknown``.
    from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

    value = resolve_ambient_session_id() or DEFAULT_SESSION_SEGMENT
    return _safe_segment(value)


def _run_segment() -> str:
    value = _first_env(RUN_ENV_KEYS) or f"pid-{os.getpid()}"
    return _safe_segment(value)


def _rooted_path(
    project: str | None,
    *parts: str,
    create_parent: bool,
) -> Path:
    path = scratch_root(project).joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _safe_segment(value: str) -> str:
    text = str(value).strip()
    if not text or text in {".", ".."}:
        raise ValueError("scratch path segment must be non-empty")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"unsafe scratch path segment: {value!r}")
    return text


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
