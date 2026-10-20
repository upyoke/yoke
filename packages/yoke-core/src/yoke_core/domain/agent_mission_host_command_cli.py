"""Lease-authorized client-local host command for exploratory walkers."""

from __future__ import annotations

from yoke_contracts.public_ref import parse_public_item_ref

import argparse
import json
import sys
from typing import Optional

from yoke_contracts.api.function_call import TargetRef


PROG = "yoke qa mission host-command"
# Yoke commands that can sit in a browser approval for its full lifetime.
_APPROVAL_WAITING_COMMANDS = frozenset({"setup", "connect", "onboard"})
_YOKE_EXECUTABLES = frozenset({"yoke", "{yoke_bin}"})


def approval_wait_warning(command: list[str], timeout_seconds: int) -> str | None:
    """Name a timeout that would stop a Yoke command mid browser approval.

    The command is stopped when the timeout passes, so an approval the human
    has not finished yet is abandoned along with it.
    """
    from yoke_contracts.machine_authorization import CODE_TTL_SECONDS

    if timeout_seconds >= CODE_TTL_SECONDS:
        return None
    for index, value in enumerate(command[:-1]):
        if (
            value.rsplit("/", 1)[-1] in _YOKE_EXECUTABLES
            and command[index + 1] in _APPROVAL_WAITING_COMMANDS
        ):
            return (
                f"{PROG}: warning: host_command_timeout_below_approval_wait: "
                f"`{command[index + 1]}` can wait up to {CODE_TTL_SECONDS}s for a "
                f"browser approval, but --timeout-seconds is {timeout_seconds}; "
                "the command is stopped at the timeout. Pass --timeout-seconds "
                f"{CODE_TTL_SECONDS} or more (at most 900) when it may wait."
            )
    return None


def _target(parsed: argparse.Namespace) -> TargetRef:
    if parsed.item is not None:
        prefix, sequence = parse_public_item_ref(parsed.item)
        if prefix is None or sequence is None:
            raise ValueError("public_item_ref_required: pass --item PREFIX-N")
        return TargetRef(
            kind="item", public_ref=f"{prefix}-{sequence}", project_id=parsed.project
        )
    if parsed.deployment_run_id is None:
        if not parsed.project:
            raise ValueError(
                "standalone_project_required: name --project for the standalone mission"
            )
        return TargetRef(kind="global", project_id=parsed.project)
    return TargetRef(
        kind="deployment_run",
        deployment_run_id=parsed.deployment_run_id,
        project_id=parsed.project,
    )


def add_mission_subject_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare how every mission client command addresses its lease."""
    subject = parser.add_mutually_exclusive_group()
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--project")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--session-id")


def resolve_mission_contract(
    parsed: argparse.Namespace,
    *,
    prog: str,
) -> Optional[dict]:
    """Return the awaiting mission's execution contract, or print why not."""
    from yoke_core.api.service_client_structured_api_adapter import build_actor
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    try:
        target = _target(parsed)
    except ValueError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return None
    response = call_qa_function(
        function_id="test_machine.mission.access",
        target=target,
        payload={
            "execution_id": parsed.execution_id,
            "requirement_id": parsed.requirement_id,
            **(
                {"cleanup": "begin", "run_id": parsed.run_id}
                if prog == "yoke qa mission walk-end"
                else {}
            ),
        },
        actor=build_actor(session_id=parsed.session_id),
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        print(f"{prog}: {code}: {message}", file=sys.stderr)
        return None
    parsed.cleanup_lease = bool((response.result or {}).get("cleanup_lease"))
    # An older server omits the run id; walk-start then prints without it.
    parsed.mission_run_id = (response.result or {}).get("run_id")
    contract = (response.result or {}).get("execution")
    if not isinstance(contract, dict):
        print(f"{prog}: no execution contract", file=sys.stderr)
        return None
    return contract


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Run one argv-shaped command through an awaiting mission's "
            "retained Test Machine lease."
        ),
        epilog=(
            "Parked walkers: a walk you parked on instruction stops "
            "heartbeating, and if the park outlives the session the stale "
            "sweep settles the execution. This command then refuses with "
            "agent_mission_access_failed, and that refusal carries the exact "
            "`yoke qa plan run ... --continue-mission` command that resumes "
            "the walk on the same host without re-running its baseline. Run "
            "the command the refusal names; do not start a fresh plan run, "
            "which resets the host and destroys the state you walked into."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument("--gui-session", action="store_true")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help=(
            "Seconds before the command and every process under it are stopped "
            "(1..900, default 60). A Yoke setup, connect or onboard call that may "
            "wait on browser approval needs 600 or more."
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(args)
    command = list(parsed.command)
    if command and command[0] == "--":
        command = command[1:]
    if (
        not command
        or len(command) > 64
        or any(not value or len(value) > 4096 for value in command)
    ):
        parser.error("ARGV must contain 1..64 non-empty bounded arguments")
    if not 1 <= parsed.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")

    warning = approval_wait_warning(command, parsed.timeout_seconds)
    if warning is not None:
        print(warning, file=sys.stderr)
    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            execute_agent_mission_host_command,
        )
        from yoke_core.domain.machine_qa_host_control import (
            register_test_machine_host_control,
        )

        register_test_machine_host_control()
        result = execute_agent_mission_host_command(
            contract,
            argv=command,
            gui_session=parsed.gui_session,
            timeout_seconds=parsed.timeout_seconds,
        )
    except Exception as exc:
        print(
            f"{PROG}: local execution failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    payload = {
        "execution_id": parsed.execution_id,
        "requirement_id": parsed.requirement_id,
        "command_arity": len(command),
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    return int(result["exit_code"])


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = [
    "add_mission_subject_arguments",
    "approval_wait_warning",
    "main",
    "resolve_mission_contract",
    "run",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
