"""``main()`` dispatcher for the deployment_runs CLI.

Argparse parser construction lives in ``deployment_runs_cli_parser``. This
module owns only the subcommand dispatch + exit-code mapping.

CLI usage::

    python3 -m yoke_core.domain.deployment_runs <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from yoke_core.domain.deployment_runs_cli_parser import build_parser
from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_create_run,
    cmd_next_id,
    cmd_remove_item,
    cmd_update,
)
from yoke_core.domain.deployment_runs_crud_query import (
    cmd_find_by_item,
    cmd_get,
    cmd_items,
    cmd_list,
)
from yoke_core.domain.deployment_runs_lineage import (
    cmd_lineage,
    cmd_lineage_create,
    cmd_lineage_final_status,
)
from yoke_core.domain.deployment_runs_preview import (
    cmd_can_cleanup_preview,
    cmd_check_preview_occupancy,
    cmd_claim_preview,
    cmd_preview_check,
    cmd_preview_claim,
    cmd_preview_release,
    cmd_resolve_target_env,
)
from yoke_core.domain.deployment_runs_qa import cmd_qa_add, cmd_qa_list, cmd_qa_update
from yoke_core.domain.deployment_runs_schema import cmd_init
from yoke_core.domain.deployment_runs_validation import (
    cmd_check_batch_compatibility,
    cmd_validate_composition,
)
from yoke_core.engines.runs_start_for_item import start_for_item


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "init":
            cmd_init()
            return 0

        elif args.command == "next-id":
            print(cmd_next_id())
            return 0

        elif args.command == "create-run":
            run_id = cmd_create_run(
                args.project,
                args.flow,
                target_env=args.target_env,
                release_lineage=args.release_lineage,
                created_by=args.created_by,
            )
            print(run_id)
            return 0

        elif args.command == "add-item":
            print(cmd_add_item(args.run_id, args.item_id))
            return 0

        elif args.command == "remove-item":
            print(cmd_remove_item(args.run_id, args.item_id))
            return 0

        elif args.command == "get":
            result = cmd_get(args.run_id, field=args.field)
            if result is None:
                print(f"Error: deployment run '{args.run_id}' not found", file=sys.stderr)
                return 1
            print(result)
            return 0

        elif args.command == "update":
            err = cmd_update(args.run_id, args.field, args.value, force=args.force)
            if err:
                print(err, file=sys.stderr)
                if "not updatable" in err or "invalid status" in err:
                    return 2
                return 1
            return 0

        elif args.command == "list":
            result = cmd_list(
                project=args.project,
                status=args.status,
                limit=args.limit,
            )
            if result:
                print(result)
            return 0

        elif args.command == "items":
            result = cmd_items(args.run_id)
            if result:
                print(result)
            return 0

        elif args.command == "find-by-item":
            result = cmd_find_by_item(args.item_id, status=args.status)
            if result:
                print(result)
            return 0

        elif args.command == "lineage":
            result = cmd_lineage(args.run_id)
            if result is None:
                print(f"Error: run '{args.run_id}' has no release_lineage", file=sys.stderr)
                return 1
            if result:
                print(result)
            return 0

        elif args.command == "lineage-create":
            print(cmd_lineage_create())
            return 0

        elif args.command == "lineage-final-status":
            print(cmd_lineage_final_status(args.lineage_id))
            return 0

        elif args.command == "qa-add":
            print(cmd_qa_add(args.run_id, args.check_name, args.source, args.blocking))
            return 0

        elif args.command == "qa-list":
            result = cmd_qa_list(args.run_id)
            if result:
                print(result)
            return 0

        elif args.command == "qa-update":
            err = cmd_qa_update(args.run_id, args.check_name, args.status)
            if err:
                print(err, file=sys.stderr)
                return 2
            return 0

        elif args.command == "validate-composition":
            ok, msg = cmd_validate_composition(args.run_id)
            if ok:
                print(msg)
                return 0
            else:
                print(msg, file=sys.stderr)
                return 1

        elif args.command == "check-batch-compatibility":
            ok, msg = cmd_check_batch_compatibility(args.project, args.flow, args.item_ids)
            if ok:
                print(msg)
                return 0
            else:
                print(msg, file=sys.stderr)
                return 1

        elif args.command == "preview-check":
            print(cmd_preview_check(args.project, args.env_name))
            return 0

        elif args.command == "preview-claim":
            print(cmd_preview_claim(args.run_id, args.project, args.env_name))
            return 0

        elif args.command == "preview-release":
            print(cmd_preview_release(args.run_id))
            return 0

        elif args.command == "check-preview-occupancy":
            print(cmd_check_preview_occupancy(args.project, args.env_name))
            return 0

        elif args.command == "claim-preview":
            print(cmd_claim_preview(
                args.run_id, args.project, args.env_name,
                env_type=args.env_type,
            ))
            return 0

        elif args.command == "can-cleanup-preview":
            allowed, msg = cmd_can_cleanup_preview(args.run_id)
            print(msg)
            return 0 if allowed else 1

        elif args.command == "resolve-target-env":
            result = cmd_resolve_target_env(args.project, args.flow, target_env_override=args.target_env)
            print(result)
            return 0

        elif args.command == "start-for-item":
            handle = start_for_item(
                args.item_id,
                project=args.project,
                flow=args.flow,
                target_env=args.target_env,
                release_lineage=args.release_lineage,
                project_repo_path=args.project_repo_path,
                created_by=args.created_by,
            )
            payload = handle.to_dict()
            stream = sys.stdout if handle.ok else sys.stderr
            print(json.dumps(payload), file=stream)
            return 0 if handle.ok else 1

        else:
            parser.print_help(sys.stderr)
            return 2

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
