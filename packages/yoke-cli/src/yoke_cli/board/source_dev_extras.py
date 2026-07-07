"""Soft-gated source-dev guards for ``yoke board rebuild``.

The source-dev tier layers developer-experience guards on top of the essential
fetch + render + write path: a file lock, a schema seed-source check,
connected-env error classification, and outcome event emission. Each guard is
meaningful only where the engine is actually usable, so it is attempted via a
soft ``importlib.import_module(...)`` (a literal module name so the installer
package-boundary test can classify the edge) inside a try/except, and skipped
silently when the engine import is unavailable. The literal string keeps the
AST import-boundary
scanner — which only flags ``import``/``from`` statements — from treating these
as hard imports; the try/except makes the dependency genuinely optional.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable, Tuple

from yoke_cli.config import machine_config
from yoke_cli.board.outcome import RebuildResult


def acquire_lock(lock_dir: Path) -> Tuple[bool, Callable[[], None]]:
    """Acquire the rebuild lock when core is present; otherwise no-op.

    Returns ``(acquired, release)`` where ``acquired`` is ``True`` when the
    rebuild may proceed and ``release`` drops the lock.
    """
    try:
        lock_helper = importlib.import_module("yoke_core.domain.lock_helper")
    except ImportError:
        return True, (lambda: None)
    config_path = machine_config.config_path()
    if not lock_helper.acquire_lock(lock_dir, config_path):
        return False, (lambda: None)
    return True, (lambda: lock_helper.release_lock(lock_dir))


def assert_seed_source(repo_root: Path) -> None:
    """Run the schema seed-source check when core is present; otherwise skip.

    Guards against a ``yoke_core`` schema module loaded from a different
    checkout than ``repo_root``.
    """
    try:
        workspace_authority = importlib.import_module(
            "yoke_core.domain.workspace_authority"
        )
        schema = importlib.import_module("yoke_core.domain.schema")
    except ImportError:
        return
    workspace_authority.assert_seed_source_under_target_root(
        getattr(schema, "__file__", None),
        repo_root,
        seed_module_name="schema",
    )


def classify_fetch_failure(plan_file: Path, exc: Exception) -> str:
    """Build the failure message, classifying connected-env errors when core is present."""
    try:
        readiness = importlib.import_module(
            "yoke_core.domain.connected_env_readiness"
        )
    except ImportError:
        readiness = None
    if readiness is not None and readiness.is_connection_unavailable_error(exc):
        return (
            "Board rebuild aborted because connected env is "
            f"unavailable: {readiness.redact(str(exc))}\n"
            f"Preserved previous {plan_file}"
        )
    return (
        f"Board data fetch/render failed: {exc}\n"
        f"Board rebuild aborted — preserving previous {plan_file}"
    )


def emit_outcome(result: RebuildResult) -> None:
    """Emit the rebuild outcome event when core is present; otherwise skip."""
    try:
        outcome = importlib.import_module("yoke_core.domain.rebuild_board_outcome")
    except ImportError:
        return
    try:
        outcome.emit(outcome.RebuildOutcome(
            result.status,
            result.exit_code,
            result.board_path,
            result.message,
        ))
    except Exception:
        # Outcome emission is a source-dev observability nicety; never let it
        # break a rebuild that already produced its file.
        pass


__all__ = [
    "acquire_lock",
    "assert_seed_source",
    "classify_fetch_failure",
    "emit_outcome",
]
