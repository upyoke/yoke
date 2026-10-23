"""Hand a walker the Yoke Machine its connect step registered.

Run ``yoke qa mission connected-machine`` right after a connect step on the
Test Machine succeeds. It reads the host's ``$HOME/.yoke/config.json``
through the mission's retained lease, records the Machine on the mission's
docket through ``test_machine.mission.record_connected_machine``, and prints
the Machine id a session launch's ``--machine`` takes.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)

PROG = "yoke qa mission connected-machine"


def _host_machine_id(contract: dict) -> str | None:
    from yoke_core.domain.agent_mission_connected_machine import host_machine_id
    from yoke_core.domain.machine_qa_host_control import (
        register_test_machine_host_control,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        HostControlExecutionContract,
        _execution,
        _mission_contract,
    )

    register_test_machine_host_control()
    # A declared companion's contract is a plain host_command contract.
    issued = (
        HostControlExecutionContract.model_validate(contract)
        if contract.get("operation") == "host_command"
        else _mission_contract(contract)
    )
    return host_machine_id(_execution(issued).control)


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Record the Yoke Machine the walk's connect step registered and "
            "print its machine_id. Run it right after a connect step on the "
            "Test Machine succeeds. A session launch's --machine takes that "
            "registered Machine id; the Test Machine itself is reached only "
            "through its lease and is never a launch target. Walk-end "
            "retires the recorded Machine."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument(
        "--test-machine",
        metavar="TEST_MACHINE",
        help=(
            "Declared case host whose connect to read; defaults to the "
            "retained driver host."
        ),
    )
    parsed = parser.parse_args(args)
    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    from yoke_core.api.service_client_structured_api_adapter import build_actor
    from yoke_core.domain.agent_mission_connected_machine import (
        ConnectedMachineRefusal,
    )
    from yoke_core.domain.agent_mission_connected_machine_function import (
        FUNCTION_ID,
    )
    from yoke_core.domain.agent_mission_host_command_cli import _target
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    try:
        machine_id = _host_machine_id(contract)
    except ConnectedMachineRefusal as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(
            f"{PROG}: connected_machine_host_unreadable ({type(exc).__name__}); "
            "restore host connectivity and rerun this command",
            file=sys.stderr,
        )
        return 2
    response = call_qa_function(
        function_id=FUNCTION_ID,
        target=_target(parsed),
        actor=build_actor(session_id=parsed.session_id),
        payload={
            "execution_id": parsed.execution_id,
            "requirement_id": parsed.requirement_id,
            "run_id": parsed.run_id,
            "machine_id": machine_id,
        },
    )
    if not response.success:
        error = response.error
        print(
            f"{PROG}: "
            + (f"{error.code}: {error.message}" if error else "no record receipt"),
            file=sys.stderr,
        )
        return 3
    result = dict(response.result or {})
    print(
        json.dumps({"requirement_id": parsed.requirement_id, **result}, sort_keys=True)
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["PROG", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
