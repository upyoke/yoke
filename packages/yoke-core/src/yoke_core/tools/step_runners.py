"""Deployment-pipeline step runner entrypoints.

Simple stage step runners the deployment pipeline in
:mod:`yoke_core.domain.deploy_pipeline` dispatches via in-process calls.
Heavier step runners own their own modules (``deploy_core_container``,
``deploy_environment_activate``).

Each step runner returns an integer exit code:

- ``exec_auto``           -> always ``0`` (no-op for stages that need no action)
- ``exec_health_check``   -> ``0`` on HTTP 2xx, ``1`` on failure. With
  ``request_id`` it sends ``x-request-id`` and requires the response to echo
  it (the Yoke core request-id propagation contract). With
  ``require_schema_ready`` the JSON body must report ``schema_ready: true``
  and must not explicitly report a pending or rollback-incompatible migration
  state (the deployed core's DB can be served by that artifact).
- ``exec_ephemeral_verify`` -> ``0`` with ``EPHEMERAL_URL=<url>`` printed on
  success, ``1`` otherwise.  Preserves the stdout contract that
  :func:`yoke_core.domain.deploy_pipeline_step_runners._dispatch_ephemeral_verify`
  parses for ``EPHEMERAL_URL=``.

The module is also usable as a CLI for ad-hoc invocation:

    python3 -m yoke_core.tools.step_runners auto
    python3 -m yoke_core.tools.step_runners health-check <url> [request-id]
    python3 -m yoke_core.tools.step_runners ephemeral-verify <project> <repo> <branch> <workflow> <domain> [sha]

The CLI exits with the same code the Python function returns.
"""

from __future__ import annotations

from yoke_core.domain.deployment_step_utilities import (
    exec_auto,
    exec_ephemeral_verify,
    exec_health_check,
)

import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: python3 -m yoke_core.tools.step_runners "
            "{auto|health-check|ephemeral-verify} [args...]",
            file=sys.stderr,
        )
        return 1
    cmd = args[0]
    rest = args[1:]
    if cmd == "auto":
        return exec_auto()
    if cmd == "health-check":
        if len(rest) not in (1, 2):
            print(
                "Usage: python3 -m yoke_core.tools.step_runners health-check "
                "<url> [request-id]",
                file=sys.stderr,
            )
            return 1
        return exec_health_check(
            rest[0], request_id=rest[1] if len(rest) == 2 else ""
        )
    if cmd == "ephemeral-verify":
        if len(rest) < 5 or len(rest) > 6:
            print(
                "Usage: python3 -m yoke_core.tools.step_runners ephemeral-verify "
                "<project> <github_repo> <branch> <workflow> <domain> [commit_sha]",
                file=sys.stderr,
            )
            return 1
        commit_sha = rest[5] if len(rest) == 6 else ""
        return exec_ephemeral_verify(
            rest[1], rest[2], rest[3], rest[4], commit_sha,
            project=rest[0],
        )
    print(f"Error: unknown step_runner '{cmd}'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
