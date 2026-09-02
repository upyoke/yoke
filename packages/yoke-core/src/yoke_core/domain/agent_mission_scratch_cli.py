"""Teardown for an exploratory mission's lease-scoped secret staging."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_contracts.qa_mission_scratch import MissionScratchIdentityError
from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchUnavailableError,
)


PROG = "yoke qa mission scratch-teardown"


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Remove the owner-only secret-staging directory this mission "
            "lease owns on the Test Machine, and prove it is gone."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parsed = parser.parse_args(args)
    if not 1 <= parsed.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")

    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return 2
    try:
        from yoke_core.domain.machine_qa_local_execution import (
            execute_agent_mission_scratch_teardown,
        )
        from yoke_core.domain.ssh_mac_host_control import (
            register_ssh_mac_host_control,
        )

        register_ssh_mac_host_control()
        result = execute_agent_mission_scratch_teardown(
            contract,
            timeout_seconds=parsed.timeout_seconds,
        )
    except (MissionScratchIdentityError, MissionScratchUnavailableError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"{PROG}: local execution failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "execution_id": parsed.execution_id,
                "requirement_id": parsed.requirement_id,
                **result,
            },
            sort_keys=True,
        )
    )
    if result["removed"]:
        return 0
    print(
        f"{PROG}: mission_scratch_not_removed: {result['scratch_path']} still "
        "exists on the Test Machine after removal exited "
        f"{result['removal_exit_code']} "
        f"({result['removal_stderr'] or 'no stderr'}). Report this as a "
        "finding against your own walk, then re-run this command; if it "
        "still refuses, the operator must remove that path on the host "
        "before the machine is handed to anyone else.",
        file=sys.stderr,
    )
    return 3


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
