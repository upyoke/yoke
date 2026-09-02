"""Lease-authorized client-local host command for exploratory walkers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_contracts.api.function_call import TargetRef


PROG = "yoke qa mission host-command"


def _target(parsed: argparse.Namespace) -> TargetRef:
    if parsed.item is not None:
        return TargetRef(kind="item", public_ref=parsed.item, project_id=parsed.project)
    if parsed.item_id is not None:
        return TargetRef(kind="item", item_id=parsed.item_id)
    return TargetRef(
        kind="deployment_run",
        deployment_run_id=parsed.deployment_run_id,
        project_id=parsed.project,
    )


def add_mission_subject_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare how every mission client command addresses its lease."""
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--item-id", type=int)
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

    response = call_qa_function(
        function_id="test_machine.mission.access",
        target=_target(parsed),
        payload={
            "execution_id": parsed.execution_id,
            "requirement_id": parsed.requirement_id,
        },
        actor=build_actor(session_id=parsed.session_id),
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        print(f"{prog}: {code}: {message}", file=sys.stderr)
        return None
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
    parser.add_argument("--timeout-seconds", type=int, default=60)
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

    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            execute_agent_mission_host_command,
        )
        from yoke_core.domain.ssh_mac_host_control import (
            register_ssh_mac_host_control,
        )

        register_ssh_mac_host_control()
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
    "main",
    "resolve_mission_contract",
    "run",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
