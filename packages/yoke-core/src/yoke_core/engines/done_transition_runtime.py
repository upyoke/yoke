"""Runtime helpers for done-transition."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    """Resolve the repo root from this engine's location."""
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> str:
    """Return the retired DB path token for legacy call signatures."""
    return ""


def _connect():
    """Open the Yoke DB with row access and busy timeout."""
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


class _Tee:
    """File-like wrapper that writes to two streams simultaneously.

    Used to mirror merge output to the real stdout while also capturing
    it for post-merge ``YOKE_REPO_ROOT`` parsing.
    """

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def write(self, data):  # type: ignore[override]
        self._primary.write(data)
        self._secondary.write(data)
        return len(data) if isinstance(data, str) else 0

    def flush(self) -> None:
        self._primary.flush()
        self._secondary.flush()

    def isatty(self) -> bool:
        try:
            return self._primary.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._primary, name)


def _rebuild_board_direct() -> None:
    """Rebuild BOARD.md in-process via the owned backlog domain."""
    from yoke_core.domain import backlog

    backlog._rebuild_board(out=sys.stderr)


def _epic_numeric(epic_id: str) -> int:
    """Return the numeric epic item id for a raw epic ref (``YOK-N`` or ``N``)."""
    raw = str(epic_id).strip()
    if raw.upper().startswith("YOK-"):
        raw = raw[4:]
    return int(raw.lstrip("#"))


def _update_task_status_direct(
    epic_id: str,
    task_num: str,
    new_status: str,
    note: str,
    *,
    env_overrides: dict[str, str] | None = None,
    no_rebuild: bool = True,
    no_github: bool = True,
    no_derive: bool = True,
) -> int:
    """Relay the epic-task status flip through the transport.

    Routes ``done_transition.epic_task_status_set`` so the cascade write runs
    over an https control plane as well as a local Postgres connection. The
    claim-bypass / done-verified values the engine used to set as process env
    vars (``env_overrides``) travel as a typed payload and are posted on a
    request-scoped ContextVar server-side; ``os.environ`` is never mutated. The
    epic ref is passed through unchanged so ``update_task_status`` queries it
    exactly as the former direct call did; the numeric epic id targets the
    relay for project-scoped authorization.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    overrides = env_overrides or {}
    resp = call_dispatcher(
        function_id="done_transition.epic_task_status_set",
        target=TargetRef(kind="item", item_id=_epic_numeric(epic_id)),
        payload={
            "epic_id": str(epic_id),
            "task_num": str(task_num),
            "status": new_status,
            "note": note,
            "claim_bypass": overrides.get("YOKE_CLAIM_BYPASS", ""),
            "status_source": overrides.get("YOKE_STATUS_SOURCE", ""),
            "task_done_verified": overrides.get("YOKE_TASK_DONE_VERIFIED", "") == "1",
            "no_rebuild": no_rebuild,
            "no_github": no_github,
            "no_derive": no_derive,
        },
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"epic task status write failed: {message}")
    return int((resp.result or {}).get("rc") or 0)


def _sync_done_item_direct(item_id: int, old_status: str) -> None:
    """Batch final GitHub sync for a done item."""
    try:
        from yoke_core.domain import backlog_github_sync
    except ImportError as exc:
        print(
            f"Warning: backlog_github_sync import failed for YOK-{item_id}: {exc}",
            file=sys.stderr,
        )
        return
    try:
        backlog_github_sync.sync_done_item(
            str(item_id), old_status, stdout=sys.stderr, stderr=sys.stderr
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"Warning: sync_done_item failed for YOK-{item_id}: {exc}",
            file=sys.stderr,
        )


def _update_item_direct(
    item_id: int,
    field: str,
    value: str,
    *,
    env_overrides: dict[str, str] | None = None,
    done_nonce_verified: bool = False,
    qa_bypass: bool | None = None,
    rebuild_board: bool = False,
    no_github: bool = False,
) -> int:
    """Relay an item field write through the transport.

    Routes ``done_transition.item_status_set`` so the done flip / delivery-stage
    redirect runs over an https control plane as well as a local Postgres
    connection. The claim-bypass / status-source the engine used to set as
    process env vars (``env_overrides``) travel as a typed payload and are
    posted on a request-scoped ContextVar server-side; ``os.environ`` is never
    mutated. The request session is the ambient session resolved by the
    dispatcher. Returns an exit-code-like int (0 on a completed write, 1 on a
    write exception) so callers keep the existing ``returncode`` checks.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    overrides = env_overrides or {}
    resp = call_dispatcher(
        function_id="done_transition.item_status_set",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={
            "field": field,
            "value": value,
            "claim_bypass": overrides.get("YOKE_CLAIM_BYPASS", ""),
            "status_source": overrides.get("YOKE_STATUS_SOURCE", ""),
            "qa_bypass": qa_bypass,
            "done_nonce_verified": done_nonce_verified,
            "no_github": no_github,
            "rebuild_board": rebuild_board,
        },
    )
    if resp.success:
        return 0
    message = resp.error.message if resp.error else "unknown error"
    print(
        f"Warning: backlog update {field}={value} for YOK-{item_id} "
        f"failed: {message}",
        file=sys.stderr,
    )
    return 1


def _run_git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    cmd = ["git"] + args
    kwargs: dict[str, Any] = {"text": True, "check": False}
    if capture:
        kwargs["capture_output"] = True
    if cwd:
        kwargs["cwd"] = str(cwd)
    return subprocess.run(cmd, **kwargs)


def _query_item_field(item_id: int, field_name: str) -> str:
    """Read a single stored item field through the connected transport.

    Relays ``done_transition.item_field`` so the read runs over an https
    control plane as well as a local Postgres connection; the returned
    value (empty string for a missing row or null column, the ``p.slug``
    for ``project``) is preserved exactly. A read failure raises, matching
    the inline ``connect()`` failure the callers never swallowed.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    resp = call_dispatcher(
        function_id="done_transition.item_field",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"field": field_name},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"item field read failed ({field_name}): {message}")
    return str((resp.result or {}).get("value") or "")


def _reseat_package_paths(
    launched_from: Path,
    repo_root: Path,
    *,
    package_prefix: str,
) -> list[str]:
    """Reseat ``__path__`` on loaded packages whose entries point under
    ``launched_from``, repointing each entry to the matching ``repo_root``
    subtree.

    Defends the lazy-submodule import path against the runner-launched-
    from-worktree-that-gets-deleted-mid-execution failure mode: the
    package object's ``__path__`` is set at first import and is sticky;
    after the worktree is deleted, subsequent submodule loads search the
    cached worktree-bound entries and fail with ``ImportError``. Updating
    the cached ``__path__`` here makes those lazy imports resolve through
    the main checkout instead.

    Returns the list of qualified module names that were reseated (for
    test introspection); production callers ignore the return value.
    """
    reseated: list[str] = []
    try:
        launched_resolved = launched_from.resolve()
    except (OSError, ValueError):
        return reseated
    try:
        repo_resolved = repo_root.resolve()
    except (OSError, ValueError):
        return reseated
    if launched_resolved == repo_resolved:
        return reseated
    for name, module in list(sys.modules.items()):
        if not (
            name == package_prefix or name.startswith(package_prefix + ".")
        ):
            continue
        paths = getattr(module, "__path__", None)
        if not paths:
            continue
        try:
            old_paths = list(paths)
        except TypeError:
            continue
        new_paths: list[str] = []
        changed = False
        for entry in old_paths:
            try:
                p = Path(entry).resolve()
            except (OSError, ValueError):
                new_paths.append(entry)
                continue
            try:
                rel = p.relative_to(launched_resolved)
            except ValueError:
                new_paths.append(entry)
                continue
            new_entry_path = repo_resolved / rel
            # Safety: skip reseat when the destination does not exist as
            # a directory. Production guarantees the main checkout's
            # subtree exists; tests with mocked repo_root values would
            # otherwise corrupt sys.modules for subsequent imports.
            if not new_entry_path.is_dir():
                new_paths.append(entry)
                continue
            new_entry = str(new_entry_path)
            new_paths.append(new_entry)
            if new_entry != entry:
                changed = True
        if changed:
            try:
                module.__path__ = new_paths
                reseated.append(name)
            except (AttributeError, TypeError):
                continue
    return reseated


def _reseat_runtime_paths(repo_root: Path | str) -> list[str]:
    """Runner-facing reseat helper. Auto-detects ``launched_from`` from the
    loaded ``runtime`` package's first ``__path__`` entry and reseats every
    ``runtime.*`` package whose paths still point under the launching
    directory at the corresponding ``repo_root`` subtree."""
    import runtime as _runtime
    pkg_path = getattr(_runtime, "__path__", None)
    if not pkg_path:
        return []
    try:
        launched_from = Path(list(pkg_path)[0]).resolve().parent
    except (OSError, ValueError, IndexError):
        return []
    return _reseat_package_paths(
        launched_from, Path(repo_root), package_prefix="runtime",
    )
