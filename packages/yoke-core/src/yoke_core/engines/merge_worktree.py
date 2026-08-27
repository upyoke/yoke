"""Merge-worktree engine public facade."""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.domain.classify_dirty_files import (  # noqa: F401
    YOKE_MANAGED_PATTERNS,
    is_yoke_managed_pattern,
)
from yoke_core.engines._merge_worktree_runtime import (  # noqa: F401
    _GIT_TIMEOUT_ENV,
    _DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS,
    _GIT_TIMEOUT_EXIT_CODE,
    _repo_root,
    _db_path,
    _connect,
    _git_command_timeout_seconds,
    _run_git,
    _run_python_module,
    _print,
    _already_merged_message,
)
from yoke_core.engines.merge_boundary_ceremony import (  # noqa: F401
    refuse_bare_standalone_merge,
)
from yoke_core.engines.merge_worktree_events import (  # noqa: F401
    _emit_merge_event,
    _fail_merge_rest,
    _fail_merge_subprocess,
)
from yoke_core.engines.merge_worktree_prepare import (  # noqa: F401
    MergeArgs,
    MergeContext,
    ConflictInfo,
    _TASK_TERMINAL_SUCCESS,
    _sql_task_terminal_success_list,
    _matches_glob,
    validate_args,
    resolve_context,
    _find_worktree,
    preflight_checks,
    check_and_clean_root_dirty_state,
    prune_agent_worktrees,
    extract_generated_files,
    _pre_merge_integration,
    _stash_classify_gate,
)
from yoke_core.engines.merge_worktree_execute import (  # noqa: F401
    classify_conflict,
    is_additive_conflict,
    resolve_conflict,
    _resolve_additive_conflict,
    auto_resolve_conflicts,
    trial_merge,
    do_rebase_or_merge,
    _terminate_process_tree,
    _run_streaming,
    run_tests,
)
from yoke_core.engines.merge_worktree_post import (  # noqa: F401
    do_local_merge,
    _current_origin_target_sha,
    _ensure_target_pushed,
    _discover_existing_pr,
    do_pr_merge,
    _wait_for_ci,
    _post_merge_cleanup,
    _sync_local_target,
    _schema_refresh,
    _yoke_state_dir,
    _regenerate_views,
    _regenerate_views_advisory,
    _ensure_target_branch,
)
from yoke_core.engines.merge_worktree_runner import run


def parse_args(argv: list[str]) -> MergeArgs:
    """Parse CLI arguments matching the shell contract."""
    args = MergeArgs(branch="")
    positional: list[str] = []

    for arg in argv:
        if arg in ("-h", "--help"):
            sys.stdout.write(
                "Usage: merge-worktree BRANCH [TARGET] [EPIC_REF] [flags]\n"
                "\n"
                "Flags:\n"
                "  --local                 Merge into local target without a PR\n"
                "  --force-lock            Take the merge lock even when held\n"
                "  --keep-remote           Leave the remote branch after merge\n"
                "  --skip-simulation       Skip the pre-merge simulation gate\n"
                "  --standalone            Permit merging a non-epic item branch\n"
                "  --local-verification    Run post-rebase verification locally\n"
                "                          even when the project declares a CI\n"
                "                          workflow (offline / deliberate local).\n"
                "                          When CI routing is selected, wall-clock\n"
                "                          while holding the merge lock is comparable\n"
                "                          to a local run; the win is freeing the\n"
                "                          local machine and admission slot, not\n"
                "                          latency.\n"
            )
            raise SystemExit(0)
        if arg == "--local":
            args.local_merge = True
        elif arg == "--force-lock":
            args.force_lock = True
        elif arg == "--keep-remote":
            args.keep_remote = True
        elif arg == "--skip-simulation":
            args.skip_simulation = True
        elif arg == "--standalone":
            args.standalone = True
        elif arg == "--local-verification":
            args.local_verification = True
        else:
            positional.append(arg)

    if positional:
        args.branch = positional[0]
    if len(positional) > 1:
        args.target = positional[1]
    if len(positional) > 2:
        args.epic_ref = positional[2]

    return args


def main(argv: Optional[list[str]] = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    args = parse_args(raw)
    # Only the command line reaches here; the boundary that owns a standalone
    # item's evidence and terminal transition drives ``run`` in-process.
    if args.standalone:
        refusal = refuse_bare_standalone_merge(args.branch)
        if refusal:
            sys.stderr.write(f"{refusal}\n")
            return 1
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
