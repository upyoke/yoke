"""``yoke runner-fleet`` source-dev/admin command adapters."""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error


RUNNER_FLEET_EXEC_USAGE = (
    "yoke runner-fleet exec --project PROJECT "
    "--settings-file STACK_CONFIG_JSON [--bootstrap-local-authority] "
    "-- <command...>"
)


def runner_fleet_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke runner-fleet exec",
        description=(
            "Run a runner-fleet admin command with AWS capability authority "
            "and an ephemeral repository-automation installation token."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project slug; must match the renderer settings snapshot.",
    )
    parser.add_argument(
        "--settings-file",
        required=True,
        type=Path,
        help="Versioned Pulumi stack-config JSON snapshot.",
    )
    parser.add_argument(
        "--bootstrap-local-authority",
        action="store_true",
        help=(
            "Recovery only: read AWS credentials from the machine capability "
            "store and mint the repository token directly from its configured "
            "App key instead of using the hosted runner broker."
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parse_or_usage_error(parser, args, RUNNER_FLEET_EXEC_USAGE)
    if parsed is None:
        return 2

    command = list(parsed.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("error: missing child command after --", file=sys.stderr)
        print(f"Usage: {RUNNER_FLEET_EXEC_USAGE}", file=sys.stderr)
        return 2

    try:
        from yoke_cli.transport.runner_fleet_token import (
            fetch_runner_fleet_token,
        )

        executor = importlib.import_module(
            "yoke_core.tools.runner_fleet_exec"
        )

        def hosted_token_loader(project, authority_intent, aws_env):
            return fetch_runner_fleet_token(
                project=project,
                authority_intent=authority_intent,
                aws_env=aws_env,
            )
        executor_kwargs = {"hosted_token_loader": hosted_token_loader}
        token_source_env = ""
        previous_token_source = None
        if parsed.bootstrap_local_authority:
            executor_kwargs["aws_env_loader"] = (
                executor.aws_machine_capability_env
            )
            token_source_env = executor.RUNNER_FLEET_TOKEN_SOURCE_ENV
            previous_token_source = os.environ.get(token_source_env)
            os.environ[token_source_env] = "local"
        try:
            return int(executor.execute_runner_fleet_command(
                parsed.project,
                parsed.settings_file,
                command,
                **executor_kwargs,
            ))
        finally:
            if token_source_env:
                if previous_token_source is None:
                    os.environ.pop(token_source_env, None)
                else:
                    os.environ[token_source_env] = previous_token_source
    except FileNotFoundError:
        print(
            f"error: child executable not found on PATH: {command[0]}",
            file=sys.stderr,
        )
        return 127
    except Exception as exc:
        print(f"error: runner-fleet exec failed: {exc}", file=sys.stderr)
        return 1


__all__ = ["RUNNER_FLEET_EXEC_USAGE", "runner_fleet_exec"]
