"""Workspace anchor for the agents_render writer family.

Owns the helpers that the renderer's writer hot path used to inline:

- ``_repo_root``: resolves the repo root via ``git rev-parse --show-toplevel``
  with a ``Path(__file__)`` walk-up fallback. Reserved for the CLI fallback
  path; writer functions never call it.
- ``resolve_target_root_for_cli``: chooses an explicit ``target_root`` from a
  command-line argument or ``$YOKE_RENDER_TARGET_ROOT`` env var. Falls back
  to ``_repo_root`` only when neither is provided AND the cwd is not inside a
  linked git worktree.
- ``require_reader_root``: strict resolver for the renderer's reader hot
  path. Prefers an explicit ``target_root``, then ``$YOKE_BOUND_WORKSPACE``
  as a legacy fallback for reader-only callers, and raises ``RuntimeError``
  when neither is supplied. The opt-in ``allow_ambient=True`` keyword
  unlocks the ``_repo_root`` fallback for legitimate CLI consumers.

The writer-side guard previously owned here lives in
:mod:`yoke_core.domain.workspace_authority`
(``assert_target_under_session_work_authority``) and validates the
calling session's live ``work_claims`` rows rather than the stale
``$YOKE_BOUND_WORKSPACE`` env-var snapshot.

The writer hot path requires every public renderer entry point to take
``target_root`` as a required keyword argument; the reader hot path now
funnels through ``require_reader_root`` so silent ambient-cwd resolution is
no longer reachable through the substrate renderer's public surface.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_contracts.project_contract.workspace_roots import (
    BOUND_WORKSPACE_ENV_VAR,
    RENDER_TARGET_ROOT_ENV_VAR,
    _is_inside_linked_worktree,
    _repo_root,
    resolve_target_root_for_cli as _resolve_target_root_for_cli,
)


def require_reader_root(
    target_root: Optional[Path],
    *,
    allow_ambient: bool = False,
) -> Path:
    """Resolve ``target_root`` for renderer reader helpers; refuse silent cwd.

    Precedence:

    1. ``target_root`` when provided — caller-supplied anchor always wins.
    2. ``$YOKE_BOUND_WORKSPACE`` when set and non-empty — the
       SessionStart-exported session anchor.
    3. ``_repo_root()`` only when ``allow_ambient=True`` (CLI / explicit
       opt-in path for tooling that genuinely wants the ambient repo root).

    When neither ``target_root`` nor ``YOKE_BOUND_WORKSPACE`` is set AND
    ``allow_ambient`` is False, raise ``RuntimeError`` naming both missing
    inputs. The error message is structured so the operator immediately
    sees which input to supply.
    """
    if target_root is not None:
        return Path(target_root)
    workspace = os.environ.get(BOUND_WORKSPACE_ENV_VAR, "").strip()
    if workspace:
        return Path(workspace).resolve()
    if allow_ambient:
        return _repo_root().resolve()
    raise RuntimeError(
        "agents_render reader: no anchor available. "
        "target_root was not supplied and "
        f"${BOUND_WORKSPACE_ENV_VAR} is unset. "
        "Pass target_root=<path> to the reader, set the env var via the "
        "SessionStart hook, or call the helper with allow_ambient=True from "
        "a CLI surface that explicitly opts into cwd-based resolution."
    )


def resolve_target_root_for_cli(
    arg_value: Optional[str] = None,
    *,
    env_var: str = RENDER_TARGET_ROOT_ENV_VAR,
) -> Path:
    """Resolve ``target_root`` from CLI arg, env var, or repo-root fallback.

    Precedence:

    1. ``arg_value`` (typically the ``--target-root`` flag) when truthy.
    2. ``os.environ[env_var]`` when set and non-empty.
    3. ``_repo_root()`` only when both above are unset AND the cwd is not
       inside a linked git worktree. Linked-worktree cwd without an explicit
       anchor raises ``RuntimeError`` so the operator surfaces the ambiguity
       before any file is written.
    """
    return _resolve_target_root_for_cli(
        arg_value,
        env_var=env_var,
        repo_root=_repo_root,
        is_inside_linked_worktree=_is_inside_linked_worktree,
    )


def run_cli(*, write_all, detect_substrate_drift) -> None:
    """CLI entry consumed by ``agents_render``'s ``__main__`` block.

    Lifted out so the writer module stays under the file-line cap; the writer
    callables are dependency-injected to avoid an ``agents_render`` import at
    module load.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="agents_render")
    parser.add_argument("command", choices=("render", "check", "dry-run"))
    parser.add_argument(
        "--target-root",
        default=None,
        help="Defaults to $YOKE_RENDER_TARGET_ROOT, then to git rev-parse "
        "--show-toplevel when neither is set and cwd is not in a linked worktree.",
    )
    args = parser.parse_args()
    try:
        target_root = resolve_target_root_for_cli(args.target_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    if args.command == "check":
        drifted = detect_substrate_drift(target_root=target_root)
        if drifted:
            for d in drifted:
                print(d, file=sys.stderr)
            sys.exit(1)
        print("No drift detected.")
        return
    results = write_all(target_root=target_root, dry_run=(args.command == "dry-run"))
    for path, (action, _) in sorted(results.items()):
        print(f"{action}: {path}")


__all__ = [
    "BOUND_WORKSPACE_ENV_VAR",
    "RENDER_TARGET_ROOT_ENV_VAR",
    "_repo_root",
    "_is_inside_linked_worktree",
    "require_reader_root",
    "resolve_target_root_for_cli",
    "run_cli",
]
