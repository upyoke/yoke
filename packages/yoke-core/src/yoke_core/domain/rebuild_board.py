"""Board rebuild — fetch board data via the dispatcher, render locally.

One composition for both transports: the data fetch is a
``board.data.get`` function call (relayed over https on an
https-default machine, dispatched in-process against the connected
Postgres otherwise); the render consumes the returned payload together
with the client-local inputs (``.yoke/board.json``, board art, the
rendered VISION doc, the machine commit cache) and writes
``.yoke/BOARD.md`` + its timestamp file locally.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_core.domain import machine_config, rebuild_board_outcome as outcome, schema
from yoke_core.domain.rebuild_board_file_write import write_live_text
from yoke_core.domain.rebuild_board_render import (
    BoardDataFetchError,
    build_board_file_text,
)
from yoke_core.domain.lock_helper import acquire_lock, release_lock
from yoke_core.domain.workspace_authority import (
    assert_seed_source_under_target_root,
)

THROTTLE_SECONDS = 5


def _strip_worktree_path(path: Path) -> Path:
    parts = list(path.parts)
    if ".worktrees" in parts:
        return Path(*parts[:parts.index(".worktrees")])
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return Path(*parts[:i])
    return path


def _find_repo_root(start: Path) -> Path | None:
    current = start.expanduser()
    if current.is_file():
        current = current.parent
    try:
        current = current.resolve()
    except OSError:
        return None
    git_root = _git_root(current)
    if git_root is not None:
        return git_root
    for candidate in (current, *current.parents):
        if (candidate / ".yoke").is_dir() or (candidate / "runtime").is_dir():
            return candidate
    return None


def _git_root(start: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def resolve_main_repo_root(repo_arg: str | None = None) -> Path:
    if repo_arg:
        found = _find_repo_root(Path(repo_arg))
        if found:
            return _strip_worktree_path(found)
        return _strip_worktree_path(Path(repo_arg).resolve())

    for env_name in ("CLAUDE_PROJECT_DIR",):
        env_value = os.environ.get(env_name)
        if env_value:
            found = _find_repo_root(Path(env_value))
            if found:
                return _strip_worktree_path(found)
            return _strip_worktree_path(Path(env_value).resolve())

    git_root = _git_root(Path.cwd())
    if git_root is not None:
        return git_root

    found = _find_repo_root(Path.cwd())
    if found:
        return _strip_worktree_path(found)

    raise FileNotFoundError("Could not find project repo root.")


def try_resolve_main_repo_root(repo_arg: Optional[str] = None) -> Optional[Path]:
    """Like :func:`resolve_main_repo_root` but returns ``None`` when no local
    checkout exists, instead of raising.

    Server-side (no ``.git``, no ``CLAUDE_PROJECT_DIR``, server cwd not a repo)
    both the ``FileNotFoundError`` raised here and the worktree/find_repo_root
    ``RuntimeError`` mean "no local checkout" — the board is a client-local view
    the in-checkout client rebuilds, so callers skip rather than fail.
    """
    try:
        return resolve_main_repo_root(repo_arg)
    except (FileNotFoundError, RuntimeError):
        return None


def rebuild_one(
    *,
    repo_root: Path,
    board_path: Path,
    force: bool,
    scope: str,
    emit: bool = True,
    phase_recorder: PhaseRecorder | None = None,
) -> outcome.RebuildOutcome:
    plan_file = board_path
    board_ts_file = Path(f"{plan_file}.ts")

    if not force and board_ts_file.is_file():
        try:
            last_rebuild = int(board_ts_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            last_rebuild = 0
        if int(time.time()) - last_rebuild < THROTTLE_SECONDS:
            result = outcome.throttled(plan_file, THROTTLE_SECONDS)
            if emit:
                outcome.emit(result)
            return result

    lock_dir = Path(f"{plan_file}.lock")
    config_path = machine_config.config_path()
    acquired = False

    try:
        with measure_phase(phase_recorder, "lock"):
            if not acquire_lock(lock_dir, config_path):
                result = outcome.lock_skipped(plan_file)
                if emit:
                    outcome.emit(result)
                return result
        acquired = True

        try:
            merged = build_board_file_text(
                repo_root=repo_root,
                board_path=plan_file,
                scope=scope,
                phase_recorder=phase_recorder,
            )
        except Exception as exc:
            from yoke_core.domain import connected_env_readiness as _readiness

            if _readiness.is_connection_unavailable_error(exc):
                msg = (
                    "Board rebuild aborted because connected env is "
                    f"unavailable: {_readiness.redact(str(exc))}\n"
                    f"Preserved previous {plan_file}"
                )
            else:
                msg = (
                    f"Board data fetch/render failed: {exc}\n"
                    f"Board rebuild aborted — preserving previous {plan_file}"
                )
            result = outcome.failed(plan_file, msg)
            if emit:
                outcome.emit(result)
            return result

        # plan_file and board_ts_file are untracked generated project views
        # under .yoke/ — regenerated from DB state on status changes.
        # The seed-source check catches Coupling B (schema imported from a
        # different checkout than the resolved repo_root).
        assert_seed_source_under_target_root(
            getattr(schema, "__file__", None),
            repo_root,
            seed_module_name="schema",
        )
        with measure_phase(phase_recorder, "file_write"):
            plan_file.parent.mkdir(parents=True, exist_ok=True)
            write_live_text(plan_file, merged)
            board_ts_file.write_text(f"{int(time.time())}\n", encoding="utf-8")
        result = outcome.rebuilt(plan_file)
        if emit:
            outcome.emit(result)
        return result
    finally:
        if acquired:
            release_lock(lock_dir)


def rebuild(
    *,
    repo_arg: str | None = None,
    force: bool = False,
    output_name: str | None = None,
    scope: str | None = None,
    emit: bool = True,
    phase_recorder: PhaseRecorder | None = None,
) -> outcome.RebuildOutcome:
    repo_root = resolve_main_repo_root(repo_arg)

    board_path = resolve_board_path(repo_root, output_name)
    if not scope:
        scope = machine_config.board_scope(repo_root)

    return rebuild_one(
        repo_root=repo_root,
        board_path=board_path,
        force=force,
        scope=scope,
        emit=emit,
        phase_recorder=phase_recorder,
    )


def render_text(
    *,
    repo_arg: str | None = None,
    output_name: str | None = None,
    scope: str | None = None,
    phase_recorder: PhaseRecorder | None = None,
) -> tuple[Path, Path, str]:
    """Return ``(repo_root, board_path, content)`` without writing files."""
    repo_root = resolve_main_repo_root(repo_arg)
    board_path = resolve_board_path(repo_root, output_name)
    if not scope:
        scope = machine_config.board_scope(repo_root)
    content = build_board_file_text(
        repo_root=repo_root,
        board_path=board_path,
        scope=scope,
        phase_recorder=phase_recorder,
    )
    return repo_root, board_path, content


def resolve_board_path(repo_root: Path, output_name: str | None = None) -> Path:
    if not output_name:
        return machine_config.board_render_path(repo_root)
    return _board_path_for_output(repo_root, output_name)


def _board_path_for_output(repo_root: Path, output_name: str) -> Path:
    selected = Path(output_name).expanduser()
    if selected.is_absolute():
        return selected
    if len(selected.parts) == 1:
        return machine_config.board_render_path(repo_root).with_name(output_name)
    return repo_root / selected


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m yoke_core.domain.rebuild_board")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", dest="output_name")
    parser.add_argument("--scope")
    parser.add_argument("repo_root", nargs="?")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        return int(rebuild(
            repo_arg=args.repo_root,
            force=args.force,
            output_name=args.output_name,
            scope=args.scope,
        ))
    except FileNotFoundError:
        print("Error: Could not find project repo root.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
