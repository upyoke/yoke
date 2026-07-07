"""Done-transition engine public facade."""

from __future__ import annotations

import re
import sys

from yoke_core.engines.done_transition_runtime import (  # noqa: F401
    _repo_root,
    _db_path,
    _connect,
    _Tee,
    _rebuild_board_direct,
    _update_task_status_direct,
    _sync_done_item_direct,
    _update_item_direct,
    _run_git,
    _query_item_field,
)
from yoke_core.engines.done_transition_result import TransitionResult  # noqa: F401
from yoke_core.engines.done_transition_gates import (  # noqa: F401
    _resolve_repo_root,
    _resolve_project_context,
    _get_base_branch,
    _check_simulation_gate,
    _check_blocked_flag,
    _check_merge_guard,
    _check_empty_branch,
    _check_recovery,
    _verify_recovery_evidence,
    _handle_resume_from_step6,
    _check_deployment_redirect,
    _check_deployment_flow_guard,
    _check_deployment_evidence,
    _get_latest_run_status,
    _check_run_stage_consistency,
    _check_run_qa_gates,
    _cascade_release_to_children,
)
from yoke_core.engines.done_transition_cascade import (  # noqa: F401
    _populate_merged_at,
    _update_status_to_done,
    _cascade_epic_tasks_to_done,
    _batch_github_sync_tasks,
    _cross_project_commit_guard,
    _pre_merge_commit,
    _do_merge,
    _cleanup_stale_branches,
    _cleanup_trial_branches,
    _verify_cwd_after_merge,
    _schema_gate,
    _handle_already_done,
    _load_discovery_metadata,
    _apply_discovery_scan,
)
from yoke_core.engines.done_transition_finalize import (  # noqa: F401
    _finalize_done_local_side_effects,
)
from yoke_core.engines.done_transition_runner import run

def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the done-transition state machine."""
    args = argv if argv is not None else sys.argv[1:]

    item_id: int | None = None
    env_name = ""
    skip_simulation = False
    skip_deploy = False
    skip_qa = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--env":
            i += 1
            if i < len(args):
                env_name = args[i]
        elif arg == "--skip-simulation":
            skip_simulation = True
        elif arg == "--skip-deploy":
            skip_deploy = True
        elif arg == "--skip-qa":
            skip_qa = True
        elif item_id is None:
            cleaned = re.sub(r"^[Yy][Oo][Kk]-", "", arg).lstrip("0")
            if not cleaned.isdigit():
                print(f"Error: unexpected argument: {arg}", file=sys.stderr)
                return 2
            item_id = int(cleaned)
        else:
            print(f"Error: unexpected argument: {arg}", file=sys.stderr)
            return 2
        i += 1

    if item_id is None:
        print(
            "Usage: python3 -m yoke_core.engines.done_transition "
            "<item-number> [--env <env-name>]",
            file=sys.stderr,
        )
        return 2

    return run(
        item_id,
        env_name=env_name,
        skip_simulation=skip_simulation,
        skip_deploy=skip_deploy,
        skip_qa=skip_qa,
    )

if __name__ == "__main__":
    sys.exit(main())
