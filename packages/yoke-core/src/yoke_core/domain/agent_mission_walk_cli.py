"""Start and end one exploratory mission walk on its leased Test Machine.

``walk-start`` puts the machine in the mission's declared starting state
before the walker's first host command. ``walk-end`` uninstalls and retires
every Yoke project the walk created on the machine, removes the mission's
owner-only secret staging, restores the declared starting state, and records
that restore on the mission's run. Walk one mission at a time: every mission
of a plan shares the plan's one Test Machine lease.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_contracts.qa_mission_scratch import (
    STALE_OWNER_MARKER,
    MissionScratchIdentityError,
)
from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)
from yoke_core.domain.machine_qa_chain_restore import (
    STARTING_STATE_RESTORE,
    restore_summary,
)
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchUnavailableError,
)
from yoke_core.domain.machine_qa_mission_walk import FIXTURE_PROJECTS

PROG_START = "yoke qa mission walk-start"
PROG_END = "yoke qa mission walk-end"


def _register() -> None:
    from yoke_core.domain.machine_qa_host_control import (
        register_test_machine_host_control,
    )

    register_test_machine_host_control()


def run_start(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG_START,
        description=(
            "Reset the Test Machine to this mission's declared baseline, "
            "restore its declared OS packages, and stage its scratch. Run it "
            "before the walk's first host command. Its output names run_id, "
            "the mission's capture run that walk-end --run-id takes."
        ),
    )
    add_mission_subject_arguments(parser)
    parsed = parser.parse_args(args)
    contract = resolve_mission_contract(parsed, prog=PROG_START)
    if contract is None:
        return 2
    from yoke_core.domain.machine_qa_mission_walk import (
        execute_agent_mission_walk_start,
    )

    _register()
    prepared = execute_agent_mission_walk_start(contract)
    run_id = getattr(parsed, "mission_run_id", None)
    if run_id:
        prepared["run_id"] = int(run_id)
    print(json.dumps(prepared, sort_keys=True))
    preparation = prepared["preparation"]
    if preparation["ok"]:
        return 0
    failure = preparation["evidence"]["preparation_failure"]
    print(
        f"{PROG_START}: {preparation['error_code']}: {failure['diagnostic']}. "
        f"Recovery: {failure['recovery']}. Do not walk this mission until "
        "walk-start succeeds; report the failure as the walk's blocker.",
        file=sys.stderr,
    )
    return 3


def run_end(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG_END,
        description=(
            "Uninstall every Yoke project the walk registered on the Test "
            "Machine, cancel its open items and retire it, remove the "
            "mission's owner-only secret staging, restore the Test Machine "
            "to the mission's declared starting state, and record that "
            "restore and the fixture_project_disposal receipt on the "
            "mission's run (--run-id). Unresolved disposal removes secret "
            "staging but preserves the host and owner custody; resolve the "
            "named cause and retry through the same owner's walk-end."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parsed = parser.parse_args(args)
    if not 1 <= parsed.timeout_seconds <= 900:
        parser.error("--timeout-seconds must be between 1 and 900")
    contract = resolve_mission_contract(parsed, prog=PROG_END)
    if contract is None:
        return 2
    from yoke_core.api.service_client_structured_api_adapter import build_actor
    from yoke_core.domain.machine_qa_mission_walk import (
        execute_agent_mission_project_uninstall,
        execute_agent_mission_walk_end,
        record_mission_restore,
    )

    result = None
    cleanup_error = None
    # Disposal settles before anything is restored or released: a restore
    # erases the host evidence, and a finished cleanup ends the execution.
    disposal_failures: list[str] | None = None
    try:
        _register()
        fixture_projects = execute_agent_mission_project_uninstall(
            contract, timeout_seconds=parsed.timeout_seconds
        )
        disposal_failures, notices, recorded = _dispose_fixture_projects(
            parsed, fixture_projects
        )
        if not recorded and not disposal_failures:
            disposal_failures = [
                "fixture_project_disposal_unrecorded: no receipt; retry walk-end"
            ]
        for notice in notices:
            print(f"{PROG_END}: {notice}", file=sys.stderr)
        if disposal_failures or not recorded:
            for failure in disposal_failures:
                print(f"{PROG_END}: {failure}", file=sys.stderr)
            print(json.dumps({FIXTURE_PROJECTS: fixture_projects}, sort_keys=True))
            staging = execute_agent_mission_walk_end(
                contract, timeout_seconds=parsed.timeout_seconds, restore_host=False
            )
            print(json.dumps(staging, sort_keys=True))
            print(
                f"{PROG_END}: "
                f"{'fixture_project_disposal_unsettled' if recorded else 'fixture_project_disposal_unrecorded'}: the Test "
                "Machine was left unrestored so a rerun can find its projects; "
                "resolve the named cause under the existing owner and rerun "
                "this same walk-end; do not reset the host",
                file=sys.stderr,
            )
            if not staging["removed"] or not staging["stale_owner_marker_removed"]:
                print(
                    f"{PROG_END}: mission_scratch_not_removed: restore host write "
                    "access to the named scratch and rerun this walk-end",
                    file=sys.stderr,
                )
            if getattr(parsed, "cleanup_lease", False):
                print(
                    f"{PROG_END}: mission_cleanup_deferred: cleanup lease stays "
                    "held; retry this walk-end. To give up the host, run "
                    f"yoke claims work release --claim-id {contract['lease_id']} "
                    "--reason 'fixture disposal unsettled'",
                    file=sys.stderr,
                )
            return 3
        result = execute_agent_mission_walk_end(
            contract, timeout_seconds=parsed.timeout_seconds
        )
        result[FIXTURE_PROJECTS] = fixture_projects
    except (MissionScratchIdentityError, MissionScratchUnavailableError) as exc:
        print(f"{PROG_END}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"{PROG_END}: mission_teardown_failed ({type(exc).__name__}); "
            "restore host connectivity and rerun this walk-end",
            file=sys.stderr,
        )
        return 2
    finally:
        # A cleanup lease is released only once disposal settled, so a rerun
        # still has a live execution to dispose of the remaining projects.
        if getattr(parsed, "cleanup_lease", False) and disposal_failures == []:
            try:
                cleanup_error = _finish_cleanup(parsed, contract, result)
            except Exception as exc:
                cleanup_error = (
                    f"mission_cleanup_unsettled ({type(exc).__name__}); "
                    "restore control-plane access and rerun this walk-end"
                )
            if cleanup_error:
                print(f"{PROG_END}: {cleanup_error}", file=sys.stderr)
    restore = result[STARTING_STATE_RESTORE]
    unrecorded = (
        cleanup_error
        if getattr(parsed, "cleanup_lease", False)
        else record_mission_restore(
            requirement_id=parsed.requirement_id,
            run_id=parsed.run_id,
            restore=restore,
            actor=build_actor(session_id=parsed.session_id),
        )
    )
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
    failures = list(disposal_failures or [])
    if not result["stale_owner_marker_removed"]:
        failures.append(
            f"stale_owner_marker_not_removed: ~/{STALE_OWNER_MARKER} is still "
            "on the Test Machine. Nothing reads it; restore the host user's "
            "write access to that file, then re-run this command"
        )
    if not result["removed"]:
        failures.append(
            f"mission_scratch_not_removed: {result['scratch_path']} still "
            f"exists after removal exited {result['removal_exit_code']} "
            f"({result['removal_stderr'] or 'no stderr'}). Report this as a "
            "finding against your own walk, then re-run this command; if it "
            "still refuses, the operator must remove that path on the host "
            "before the machine is handed to anyone else"
        )
    if "baseline" in restore and not restore["restored"]:
        failures.append(f"starting_state_restore_failed: {restore_summary(restore)}")
    if unrecorded is not None:
        failures.append(
            f"starting_state_restore_unrecorded: {unrecorded}; re-run this "
            "command once the run accepts artifacts"
        )
    for failure in failures:
        print(f"{PROG_END}: {failure}", file=sys.stderr)
    return 3 if failures else 0


def _dispose_fixture_projects(
    parsed, fixture_projects: dict
) -> tuple[list[str], list[str], bool]:
    """Dispose of the walk's projects; return failures, notices, and if recorded."""
    if fixture_projects["error"]:
        return [fixture_projects["error"]], [], False
    from yoke_core.api.service_client_structured_api_adapter import build_actor
    from yoke_core.domain.agent_mission_host_command_cli import _target
    from yoke_core.domain.agent_mission_project_disposal import (
        request_project_disposal,
    )

    try:
        return request_project_disposal(
            target=_target(parsed),
            actor=build_actor(session_id=parsed.session_id),
            execution_id=parsed.execution_id,
            requirement_id=parsed.requirement_id,
            run_id=parsed.run_id,
            host_projects=fixture_projects["host_projects"],
        )
    except Exception as exc:
        return (
            [
                f"fixture_project_disposal_failed ({type(exc).__name__}); restore "
                "control-plane access and rerun this walk-end"
            ],
            [],
            False,
        )


def _finish_cleanup(parsed, contract: dict, result: dict | None) -> str | None:
    from yoke_core.api.service_client_structured_api_adapter import build_actor
    from yoke_core.domain.agent_mission_host_command_cli import _target
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id="test_machine.mission.access",
        target=_target(parsed),
        actor=build_actor(session_id=parsed.session_id),
        payload={
            "execution_id": parsed.execution_id,
            "requirement_id": parsed.requirement_id,
            "cleanup": "finish",
            "run_id": parsed.run_id,
            "lease_id": contract["lease_id"],
            "restore": result[STARTING_STATE_RESTORE] if result else None,
        },
    )
    if response.success:
        return None
    error = response.error
    return (
        (
            f"mission_cleanup_unsettled: {error.code}: {error.message}; "
            "rerun this walk-end to finish cleanup and release its lease"
        )
        if error
        else ("mission_cleanup_unsettled: no finish receipt; rerun this walk-end")
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["start"]:
        return run_start(args[1:])
    if args[:1] == ["end"]:
        return run_end(args[1:])
    print("usage: agent_mission_walk_cli (start|end) ...", file=sys.stderr)
    return 2


__all__ = ["main", "run_end", "run_start"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
