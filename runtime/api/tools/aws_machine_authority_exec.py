"""Run the AWS CLI with machine-local capability credentials, no DB read.

Source-dev/admin recovery helper: materializes the machine-local aws-admin
capability secrets for a project (``aws_machine_capability_env``) into a
subprocess environment and executes the AWS CLI there. Exists for recovery
environments where the connected env is https-transport and the wrapped
``yoke aws exec`` resolver cannot reach a local-postgres authority.
Secret values are never printed.

The child command defaults to the AWS CLI; pass ``--argv`` to run any
other executable (e.g. ``yoke runner-fleet exec ...``) under the same
materialized environment.

Usage:
    uv run --frozen python3 -m runtime.api.tools.aws_machine_authority_exec \
        --project platform --region us-east-1 -- sts get-caller-identity
    uv run --frozen python3 -m runtime.api.tools.aws_machine_authority_exec \
        --project platform --region us-east-1 --argv -- yoke --version
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from yoke_core.domain.deploy_remote import aws_machine_capability_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aws_machine_authority_exec",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--argv",
        action="store_true",
        help="Treat the trailing arguments as a full command, not AWS CLI args.",
    )
    parser.add_argument("child_args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(argv)

    child_args = list(parsed.child_args)
    if child_args and child_args[0] == "--":
        child_args = child_args[1:]
    if not child_args:
        print("error: missing child arguments after --", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.update(aws_machine_capability_env(parsed.project, parsed.region))
    command = child_args if parsed.argv else ["aws", *child_args]
    completed = subprocess.run(command, env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
