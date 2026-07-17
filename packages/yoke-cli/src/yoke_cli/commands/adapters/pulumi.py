"""Client-local typed Pulumi execution adapter."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.pulumi_stack_config_loader import (
    load_pulumi_stack_config,
)


PULUMI_EXEC_USAGE = (
    "yoke pulumi exec --project NAME --stack STACK -- "
    "<preview|refresh|import args>"
)


def pulumi_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke pulumi exec",
        description=(
            "Run one stack-bound Pulumi preview, refresh, or file import with "
            "ephemeral capability-owned authority."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--stack", required=True)
    add_session_arg(parser)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parse_or_usage_error(parser, args, PULUMI_EXEC_USAGE)
    if parsed is None:
        return 2
    command = list(parsed.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(f"Usage: {PULUMI_EXEC_USAGE}", file=sys.stderr)
        return 2
    ensure_handlers_loaded()

    def config_loader(project: str, stack: str):
        response = call_dispatcher(
            function_id="projects.pulumi_stack_config.get",
            target=TargetRef(kind="global"),
            payload={"project": project, "stack": stack},
            actor=build_actor(session_id=parsed.session_id),
        )
        if not response.success:
            message = response.error.message if response.error else "request failed"
            raise RuntimeError(message)
        return load_pulumi_stack_config(project, stack)

    try:
        renderer_values = importlib.import_module(
            "yoke_core.domain.project_renderer_values"
        )
        executor = importlib.import_module("yoke_core.tools.pulumi_exec")
        return executor.execute_pulumi_command(
            parsed.project,
            parsed.stack,
            command,
            config_loader=config_loader,
            project_root=Path(renderer_values._resolve_project_root()),
        )
    except FileNotFoundError as exc:
        print(f"error: Pulumi executable or template not found: {exc}", file=sys.stderr)
        return 127
    except Exception as exc:
        print(f"error: pulumi exec failed: {exc}", file=sys.stderr)
        return 1


__all__ = ["PULUMI_EXEC_USAGE", "pulumi_exec"]
