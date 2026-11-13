"""Client-local typed Pulumi execution adapter."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import subprocess
import sys
from typing import List, Mapping

from yoke_cli.commands._helpers import (
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.config import existing_project_lookup, machine_config
from yoke_cli.transport.pulumi_github_authority import (
    build_pulumi_github_auth_loader,
)
from yoke_cli.transport.runner_fleet_token import (
    fetch_repository_provider_token,
)


PULUMI_EXEC_USAGE = (
    "yoke pulumi exec --project NAME --stack STACK "
    "[--bootstrap-local-authority] [--confirm-destroy STACK] [--session-id S] -- "
    "<init|preview|refresh|import|up|destroy|stack rm|stack output args>"
)


def pulumi_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke pulumi exec",
        description=(
            "Run one stack-bound Pulumi initialization, preview, refresh, "
            "single-output read, file import, or operator-confirmed update with "
            "ephemeral capability-owned authority. The stack runs from its "
            "checked-in infra/Pulumi.<stack>.yaml: a temp copy of infra/ with "
            "Yoke-owned values added under the reserved yoke: config namespace "
            "(read them with pulumi.Config(\"yoke\")); the file may set only "
            "yoke:github_access (metadata, the default; variables; "
            "runner_fleet). A stack without that file is refused. "
            "`init --secrets-provider <awskms URI>` (pinned to the project's "
            "pulumi-state KMS key) prints the secretsprovider and encryptedkey "
            "lines to commit into the stack file; Yoke stores neither. Preview "
            "and up accept repeated `--target URN` or `--target=URN` for literal "
            "resources in the requested stack and the infra/Pulumi.yaml "
            "project. Up still requires operator confirmation with `--yes "
            "--non-interactive`. Destroy (whole stack, `--yes "
            "--non-interactive`) and `stack rm --yes` (never --force) require "
            "`--confirm-destroy <exact stack name>` and refuse while an "
            "checked-in environment consumer has an empty origin_ip. With "
            "origin_ip set, its VPS name stays a live selector. "
            "`destroy --preview-only` runs the same guard and prints the "
            "proposed deletions without confirmation or mutation; it refuses "
            "--yes and --refresh."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project that owns the Pulumi stack.",
    )
    parser.add_argument("--stack", required=True, help="Pulumi stack to run against.")
    parser.add_argument(
        "--bootstrap-local-authority",
        action="store_true",
        help=(
            "Recovery only: mint the runner-fleet repository token from "
            "capability-owned local AWS authority."
        ),
    )
    parser.add_argument(
        "--confirm-destroy",
        metavar="STACK",
        help=(
            "Required for mutating destroy and stack rm (not --preview-only): "
            "the exact stack name, "
            "confirming its resources or stack record are removed."
        ),
    )
    add_session_arg(parser)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Pulumi command and its arguments, e.g. preview.",
    )
    parsed = parse_or_usage_error(parser, args, PULUMI_EXEC_USAGE)
    if parsed is None:
        return 2
    command = list(parsed.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(f"Usage: {PULUMI_EXEC_USAGE}", file=sys.stderr)
        return 2
    if command[0] == "init" and parsed.bootstrap_local_authority:
        print(
            "error: --bootstrap-local-authority is limited to initialized "
            "runner-fleet stack operations and cannot be combined with init",
            file=sys.stderr,
        )
        return 2
    ensure_handlers_loaded()

    def hosted_repository_token_loader(
        project: str, authority_intent: str, aws_env: Mapping[str, str]
    ) -> str:
        return fetch_repository_provider_token(
            project=project,
            authority_intent=authority_intent,
            aws_env=aws_env,
        )

    try:
        caller_root = _current_git_root()
        project_root = _project_checkout(
            parsed.project,
            session_id=parsed.session_id,
            caller_root=caller_root,
        )
        executor = importlib.import_module("yoke_core.tools.pulumi_exec")
        return executor.execute_pulumi_command(
            parsed.project,
            parsed.stack,
            command,
            project_root=project_root,
            caller_root=caller_root,
            aws_env_loader=executor.aws_machine_capability_env,
            github_auth_loader=build_pulumi_github_auth_loader(
                session_id=parsed.session_id
            ),
            hosted_repository_token_loader=hosted_repository_token_loader,
            bootstrap_local_authority=parsed.bootstrap_local_authority,
            confirm_destroy=parsed.confirm_destroy,
        )
    except FileNotFoundError as exc:
        print(f"error: Pulumi executable or file not found: {exc}", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"error: pulumi exec failed: {exc}", file=sys.stderr)
        return 1


def _project_checkout(
    project: str,
    *,
    session_id: str | None,
    caller_root: Path | None,
) -> Path:
    """Resolve the selected project's local, project-owned Pack files."""

    response = call_dispatcher(
        function_id="projects.get",
        target=TargetRef(kind="global"),
        payload={"project": project},
        actor=build_actor(session_id=session_id),
    )
    if not response.success or not isinstance(response.result, Mapping):
        message = response.error.message if response.error else "project lookup failed"
        raise RuntimeError(message)
    row = response.result.get("row")
    if not isinstance(row, Mapping):
        raise RuntimeError("project lookup returned no project row")
    try:
        project_id = int(row["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("project lookup returned no numeric project id") from exc

    if caller_root is not None:
        reference = existing_project_lookup.find_local_project_reference(
            caller_root, config_path=None
        )
        if reference is not None and reference.project_id == project_id:
            return caller_root

    matches = [
        configured.checkout.expanduser().resolve()
        for configured in machine_config.configured_projects(existing_only=True)
        if configured.project_id == project_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"project {project!r} requires exactly one machine-local checkout "
            f"mapping; found {len(matches)}"
        )
    return matches[0]


def _current_git_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


__all__ = ["PULUMI_EXEC_USAGE", "pulumi_exec"]
