"""Import-isolated ``yoke board rebuild`` flow.

Resolve the repo root, fetch the recorded board data via ``board.data.get`` over
the CLI's own function-call transport, render markdown with the pure
``yoke_contracts.board`` renderer, then write ``.yoke/BOARD.md`` (+ its ``.ts``
timestamp sidecar) locally. None of that needs ``yoke_core``.

The source-dev tier adds developer-experience guards on top — a rebuild throttle,
a file lock, a schema seed-source check, connected-env error classification, and
outcome event emission. Those need a usable ``yoke_core`` engine, so they are
soft-gated in :mod:`yoke_cli.board.source_dev_extras` (no-ops when the engine
import is unavailable). The essential fetch + render + write path never imports
``yoke_core``.
"""

from __future__ import annotations

import dataclasses
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_cli.config import machine_config
from yoke_cli.config.checkout_context import _strip_worktree_path
from yoke_cli.board import source_dev_extras as extras
from yoke_cli.board.outcome import (
    RebuildResult,
    THROTTLED,
    failed,
    lock_skipped,
    printed,  # noqa: F401  (re-exported for the adapter's print-only path)
    rebuilt,
    throttled,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.board.art import parse_art_config
from yoke_contracts.board.config import parse_config
from yoke_contracts.board.phase_timer import PhaseRecorder, measure_phase
from yoke_contracts.board.renderer import render_board_from_payload
from yoke_contracts.board.splice import _fresh_board_text, splice_board
from yoke_contracts.board.zen import _zen_extract_vision
from yoke_contracts.project_contract.file_write import write_live_text

THROTTLE_SECONDS = 5


class BoardDataFetchError(RuntimeError):
    """``board.data.get`` returned a failure envelope."""


class BoardProjectResolutionError(RuntimeError):
    """No unique machine-configured project checkout could be resolved."""


def _normalized_path(path: Path) -> Path:
    selected = Path(_strip_worktree_path(str(path.expanduser())))
    try:
        return selected.resolve()
    except OSError:
        return selected


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _configured_project_matches(start: Path) -> list[machine_config.ConfiguredProject]:
    selected = _normalized_path(start.parent if start.is_file() else start)
    matches: list[machine_config.ConfiguredProject] = []
    for project in machine_config.configured_projects(existing_only=True):
        checkout = _normalized_path(project.checkout)
        if _contains(checkout, selected):
            matches.append(project)
    return sorted(
        matches,
        key=lambda project: len(_normalized_path(project.checkout).parts),
        reverse=True,
    )


def _configured_projects() -> list[machine_config.ConfiguredProject]:
    return machine_config.configured_projects(existing_only=True)


def _matching_configured_project_root(start: Path) -> Path | None:
    matches = _configured_project_matches(start)
    if matches:
        return _normalized_path(matches[0].checkout)
    return None


def _resolve_configured_project(start: Path, *, explicit: bool) -> Path:
    match = _matching_configured_project_root(start)
    if match is not None:
        return match
    projects = _configured_projects()
    if explicit:
        raise BoardProjectResolutionError(
            f"{start.expanduser()} is not inside a project registered in "
            "machine config; run from a registered checkout or pass one with "
            "--repo-root."
        )
    if len(projects) == 1:
        return _normalized_path(projects[0].checkout)
    if not projects:
        raise BoardProjectResolutionError(
            "no projects are registered in machine config; run `yoke onboard` "
            "or `yoke project register` first."
        )
    configured = ", ".join(
        str(_normalized_path(project.checkout)) for project in projects
    )
    raise BoardProjectResolutionError(
        "could not choose a board project from this directory; run from inside "
        f"one registered checkout or pass --repo-root. Configured projects: {configured}"
    )


def resolve_main_repo_root(repo_arg: Optional[str] = None) -> Path:
    if repo_arg:
        return _resolve_configured_project(Path(repo_arg), explicit=True)

    env_value = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_value:
        match = _matching_configured_project_root(Path(env_value))
        if match is not None:
            return match

    return _resolve_configured_project(Path.cwd(), explicit=False)


def resolve_board_path(repo_root: Path, output_name: Optional[str] = None) -> Path:
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


# ---------------------------------------------------------------------------
# Fetch + render (CLI transport + contracts render)
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S %Z")


def _parse_seed() -> Optional[int]:
    raw = os.environ.get("BOARD_SEED", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def fetch_board_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the recorded board data payload over the CLI's own transport."""
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    response = call_dispatcher(
        function_id="board.data.get",
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )
    if not response.success:
        error = response.error
        detail = (
            f"{error.code}: {error.message}" if error is not None
            else "unknown error"
        )
        raise BoardDataFetchError(f"board.data.get failed - {detail}")
    return dict(response.result or {})


def fetch_and_render(
    repo_root: Path,
    scope: str,
    phase_recorder: Optional[PhaseRecorder],
) -> str:
    root_token = str(repo_root)
    config = parse_config(None, repo_root=root_token)
    art_config = parse_art_config(None, repo_root=root_token)
    vision_entries = _zen_extract_vision(root_token)
    with measure_phase(phase_recorder, "fetch_board_data"):
        payload = fetch_board_data({
            "scope": scope,
            "config_values": dataclasses.asdict(config),
            "zen_vision_count": len(vision_entries),
            "repo_root_token": root_token,
        })
    with measure_phase(phase_recorder, "render_total"):
        return render_board_from_payload(
            payload,
            scope=scope,
            config=config,
            art_config=art_config,
            seed=_parse_seed(),
            repo_root=root_token,
            vision_entries=vision_entries,
            phase_recorder=phase_recorder,
        )


def build_board_file_text(
    *,
    repo_root: Path,
    board_path: Path,
    scope: str,
    phase_recorder: Optional[PhaseRecorder],
) -> str:
    """Return the exact BOARD.md text that write mode would persist."""
    board_content = fetch_and_render(repo_root, scope, phase_recorder)
    with measure_phase(phase_recorder, "merge_existing_board"):
        if not board_path.is_file():
            return _fresh_board_text(board_content, _timestamp())
        return splice_board(
            board_path.read_text(encoding="utf-8"),
            board_content,
            _timestamp(),
        )


# ---------------------------------------------------------------------------
# Rebuild entrypoints
# ---------------------------------------------------------------------------


def rebuild_one(
    *,
    repo_root: Path,
    board_path: Path,
    force: bool,
    scope: str,
    emit: bool = True,
    phase_recorder: Optional[PhaseRecorder] = None,
) -> RebuildResult:
    plan_file = board_path
    board_ts_file = Path(f"{plan_file}.ts")

    if not force and board_ts_file.is_file():
        try:
            last_rebuild = int(board_ts_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            last_rebuild = 0
        if int(time.time()) - last_rebuild < THROTTLE_SECONDS:
            result = throttled(plan_file, THROTTLE_SECONDS)
            if emit:
                extras.emit_outcome(result)
            return result

    lock_dir = Path(f"{plan_file}.lock")
    acquired = False
    release = lambda: None  # noqa: E731 - trivial no-op default
    try:
        with measure_phase(phase_recorder, "lock"):
            acquired, release = extras.acquire_lock(lock_dir)
        if not acquired:
            result = lock_skipped(plan_file)
            if emit:
                extras.emit_outcome(result)
            return result

        try:
            merged = build_board_file_text(
                repo_root=repo_root,
                board_path=plan_file,
                scope=scope,
                phase_recorder=phase_recorder,
            )
        except Exception as exc:
            result = failed(plan_file, extras.classify_fetch_failure(plan_file, exc))
            if emit:
                extras.emit_outcome(result)
            return result

        # BOARD.md and its .ts are untracked generated project views under
        # .yoke/, regenerated from DB state. The seed-source check (source-dev
        # only) catches a schema module loaded from a different checkout.
        extras.assert_seed_source(repo_root)
        with measure_phase(phase_recorder, "file_write"):
            plan_file.parent.mkdir(parents=True, exist_ok=True)
            write_live_text(plan_file, merged)
            board_ts_file.write_text(f"{int(time.time())}\n", encoding="utf-8")
        result = rebuilt(plan_file)
        if emit:
            extras.emit_outcome(result)
        return result
    finally:
        if acquired:
            release()


def rebuild(
    *,
    repo_arg: Optional[str] = None,
    force: bool = False,
    output_name: Optional[str] = None,
    scope: Optional[str] = None,
    emit: bool = True,
    phase_recorder: Optional[PhaseRecorder] = None,
) -> RebuildResult:
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
    repo_arg: Optional[str] = None,
    output_name: Optional[str] = None,
    scope: Optional[str] = None,
    phase_recorder: Optional[PhaseRecorder] = None,
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


__all__ = [
    "BoardDataFetchError",
    "BoardProjectResolutionError",
    "THROTTLE_SECONDS",
    "build_board_file_text",
    "fetch_and_render",
    "fetch_board_data",
    "rebuild",
    "rebuild_one",
    "render_text",
    "resolve_board_path",
    "resolve_main_repo_root",
]
