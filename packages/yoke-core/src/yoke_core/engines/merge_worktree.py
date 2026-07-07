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
    _git_env,
    _git_timeout_result,
    _run_git,
    _run_python_module,
    _print,
    _already_merged_message,
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
    _regenerate_views_or_exit5,
    _ensure_target_branch,
)
from yoke_core.engines.merge_worktree_runner import run

def parse_args(argv: list[str]) -> MergeArgs:
    """Parse CLI arguments matching the shell contract."""
    args = MergeArgs(branch="")
    positional: list[str] = []

    for arg in argv:
        if arg == "--local":
            args.local_merge = True
        elif arg == "--force-lock":
            args.force_lock = True
        elif arg == "--keep-remote":
            args.keep_remote = True
        elif arg == "--skip-simulation":
            args.skip_simulation = True
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
    return run(args)

if __name__ == "__main__":
    sys.exit(main())
