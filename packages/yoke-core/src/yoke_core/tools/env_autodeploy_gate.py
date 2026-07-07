"""Per-env auto-deploy-on-push gate for push-triggered deploy workflows.

Resolves the DB-owned per-environment policy — ``environments.settings``
must declare BOTH ``git.branch == <branch>`` AND ``deploy.auto_on_push ==
true`` (reader: ``yoke_core.domain.deploy_environment_settings
.auto_deploy_envs_for_branch``) — and reports which environments of
``<project>`` auto-deploy from a push to ``<branch>``. Consumed by
``.github/workflows/yoke-env-deploy.yml`` on push and on its
``workflow_dispatch`` retrigger lane (same branch-keyed policy question,
asked for the dispatched ref); flip the policy with
``python3 -m yoke_core.domain.projects environment-merge-settings
<env-id> --set deploy.auto_on_push=true``.

Usage::

    python3 -m yoke_core.tools.env_autodeploy_gate <project> <branch>

Prints the matching environment names one per line on exit 0.

Exit codes: 0 = at least one environment auto-deploys from this branch;
2 = refused, a resolved environment is prod (structural v0 exclusion,
regardless of declared policy); 3 = no env auto-deploys from this branch
(callers treat this as a clean no-op).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, List, Optional

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.deploy_environment_settings import (
    auto_deploy_envs_for_branch,
)
from yoke_core.domain.project_identity import resolve_project

EXIT_MATCH = 0
EXIT_PROD_REFUSED = 2
EXIT_NO_MATCH = 3

# Structural v0 exclusion: prod never auto-deploys on push, regardless of
# any deploy.auto_on_push declaration. Matched two ways: by environment
# name, and by the env's release flow (any deployment_flows row targeting
# the env whose id is the prod release flow seeded by
# yoke_core.domain.flow_init). Lifting this is a deliberate future
# slice, not a config flip.
_PROD_ENV_NAMES = frozenset({"prod", "production"})
_PROD_RELEASE_FLOW_ID = "yoke-prod-release"


def _release_flow_ids(conn: Any, project: str, env_name: str) -> List[str]:
    """Return ids of flows whose ``target_env`` is *env_name*."""
    ident = resolve_project(conn, project)
    assert ident is not None
    rows = query_rows(
        conn,
        "SELECT id FROM deployment_flows "
        "WHERE project_id=%s AND target_env=%s",
        (ident.id, env_name),
    )
    return [str(row["id"]) for row in rows]


def _prod_refusal(conn: Any, project: str, env_name: str) -> str:
    """Return the refusal reason when *env_name* is prod-shaped, else ``""``."""
    if env_name.lower() in _PROD_ENV_NAMES:
        return f"environment name '{env_name}' is the prod tier"
    if _PROD_RELEASE_FLOW_ID in _release_flow_ids(conn, project, env_name):
        return (
            f"environment '{env_name}' is the target of release flow "
            f"'{_PROD_RELEASE_FLOW_ID}'"
        )
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.env_autodeploy_gate",
        description=(
            "Resolve which environments auto-deploy on a push to <branch> "
            "(environments.settings: git.branch + deploy.auto_on_push). "
            "Exit 0 = matches printed one per line; 2 = prod refused "
            "(structural v0 exclusion); 3 = no env auto-deploys from this "
            "branch (clean no-op)."
        ),
    )
    parser.add_argument("project", help="project slug or numeric id")
    parser.add_argument("branch", help="the pushed branch name")
    args = parser.parse_args(argv)

    envs = auto_deploy_envs_for_branch(args.project, args.branch)
    if not envs:
        print(
            f"no env auto-deploys from this branch "
            f"(project '{args.project}', branch '{args.branch}'): no "
            "environment declares both git.branch matching the push and "
            "deploy.auto_on_push=true"
        )
        return EXIT_NO_MATCH

    conn = connect()
    try:
        for env_name in envs:
            reason = _prod_refusal(conn, args.project, env_name)
            if reason:
                print(
                    "REFUSED: prod auto-deploy on push is structurally "
                    f"excluded in v0 — {reason}. No deploy will run; prod "
                    "releases stay operator-attended regardless of "
                    "deploy.auto_on_push.",
                    file=sys.stderr,
                )
                return EXIT_PROD_REFUSED
    finally:
        conn.close()

    for env_name in envs:
        print(env_name)
    return EXIT_MATCH


if __name__ == "__main__":
    sys.exit(main())
