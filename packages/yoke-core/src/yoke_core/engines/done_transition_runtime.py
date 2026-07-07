"""Runtime helpers for done-transition."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from yoke_core.domain import db_backend


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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
    """Direct in-process call to ``update_status.update_task_status``."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.update_status import update_task_status

    previous: dict[str, str | None] = {}
    if env_overrides:
        for key, new_val in env_overrides.items():
            previous[key] = os.environ.get(key)
            os.environ[key] = new_val
    try:
        with db_helpers.connect() as conn:
            return update_task_status(
                conn,
                str(epic_id),
                str(task_num),
                new_status,
                note=note,
                no_rebuild=no_rebuild,
                no_github=no_github,
                no_derive=no_derive,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
    finally:
        if env_overrides:
            for key, prev in previous.items():
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev


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
    suppress_output: bool = False,
    no_github: bool = False,
) -> int:
    """Direct in-process backlog item field write.

    Calls ``yoke_core.domain.backlog.execute_update`` directly. Returns an
    exit-code-like int (0 on success, 1 on failure) so callers can preserve
    the existing ``returncode`` checks.
    """
    from yoke_core.domain import backlog

    captured = io.StringIO()
    previous: dict[str, str | None] = {}
    if env_overrides:
        for key, new_val in env_overrides.items():
            previous[key] = os.environ.get(key)
            os.environ[key] = new_val
    try:
        out = captured if suppress_output else sys.stdout
        # Status-claim verification requires the request session to be passed
        # explicitly; for this in-process direct write the request session is
        # the ambient session (env_overrides are already applied above).
        from yoke_core.domain.backlog_session_attribution import (
            _current_session_id,
        )
        kwargs: Dict[str, Any] = {
            "out": out,
            "session_id": _current_session_id(),
        }
        if done_nonce_verified:
            kwargs["done_nonce_verified"] = True
        if qa_bypass is not None:
            kwargs["qa_bypass"] = qa_bypass
        backlog.execute_update(
            str(item_id),
            field,
            value,
            rebuild_board=rebuild_board,
            no_github=no_github,
            **kwargs,
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code != 0:
            print(
                f"Warning: backlog update {field}={value} for YOK-{item_id} "
                f"exited with code {code}",
                file=sys.stderr,
            )
        return code
    except Exception as exc:
        print(
            f"Warning: backlog update {field}={value} for YOK-{item_id} "
            f"raised: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if env_overrides:
            for key, prev in previous.items():
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev
    return 0


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
    """Read a single field from items table."""
    with _connect() as conn:
        if field_name == "project":
            row = conn.execute(
                "SELECT p.slug FROM items i "
                "LEFT JOIN projects p ON p.id = i.project_id "
                f"WHERE i.id = {_p(conn)}",
                (item_id,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT {field_name} FROM items WHERE id = {_p(conn)}", (item_id,)
            ).fetchone()
    if row is None:
        return ""
    val = row[0]
    if val is None:
        return ""
    return str(val)


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
