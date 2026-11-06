"""Read-only source diagnostic for GitHub queue permissions on a bound repo."""

from __future__ import annotations

import argparse
import json

from yoke_core.domain.merge_github_check_runs import (
    read_pr_landing_and_required_checks,
)
from yoke_core.domain.merge_github_membership import read_pr_queue_membership
from yoke_core.domain.merge_github_queue import read_queue_members
from yoke_core.domain.merge_context import MergeArgs, MergeContext


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    ctx = MergeContext(
        args=MergeArgs(branch="", target=args.branch), project=args.project,
    )
    members, queue_error = read_queue_members(ctx, base_branch=args.branch)
    membership, membership_error = read_pr_queue_membership(ctx, str(args.pr))
    landing = read_pr_landing_and_required_checks(ctx, str(args.pr))
    errors = {
        "queue": queue_error,
        "membership": membership_error,
        "landing": landing.state_error,
        "checks": landing.checks_error,
    }
    passed = (
        members is not None and membership is not None
        and landing.state is not None and landing.required_checks is not None
        and not any(errors.values())
    )
    print(json.dumps({
        "project": args.project, "pull_request": args.pr, "passed": passed,
        "queue_entries_read": len(members) if members is not None else None,
        "membership_readable": membership is not None,
        "landing_readable": landing.state is not None,
        "required_checks_read": (
            len(landing.required_checks) if landing.required_checks is not None else None
        ),
        "errors": errors,
    }, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
