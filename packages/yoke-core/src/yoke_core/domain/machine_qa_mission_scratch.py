"""Lease-scoped secret staging on an exploratory mission's Test Machine.

Mission preparation creates one owner-only directory for the lease and the
mission teardown removes it, so a secret a walker must hand to a command
through a file never outlives the walk as a loose file under ``/tmp``.
Preparation also claims the host's test-project owner marker, which the
teardown clears after retiring the projects that owner created.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, Sequence
import json
from pathlib import Path
from yoke_contracts.qa_project_ownership import OWNER_FILE, OWNER_CAPABILITY

from yoke_contracts.qa_mission_scratch import (
    mission_scratch_create_argv,
    mission_scratch_path,
    mission_scratch_probe_argv,
    mission_scratch_remove_argv,
    mission_scratch_secure_argv,
)


_STDERR_EVIDENCE_LIMIT = 400


class MissionScratchHostControl(Protocol):
    """The one host-control capability scratch staging needs."""

    def run_command(
        self,
        argv: Sequence[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> Any: ...


# Answers {"state": ..., "terminal": bool} for an execution id, from the
# control plane that issued this mission's lease.
OwnerStateLookup = Callable[[str], dict[str, Any]]


class MissionScratchUnavailableError(RuntimeError):
    """Refusal naming the scratch path, the failure, and the recovery."""


def _evidence(completed: Any) -> str:
    return (getattr(completed, "stderr", "") or "").strip()[:_STDERR_EVIDENCE_LIMIT]


def create_mission_scratch(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    continues_execution_id: str | None = None,
    owner_state: OwnerStateLookup | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Create the lease's staging directory and claim the host's owner marker.

    A marker left by another execution is replaced only once ``owner_state``
    confirms that execution is terminal in the control plane, after the same
    teardown ``yoke qa mission scratch-teardown`` performs for it.
    """
    path = mission_scratch_path(execution_id)
    for argv in (
        mission_scratch_create_argv(path),
        mission_scratch_secure_argv(path),
    ):
        completed = control.run_command(list(argv), timeout=timeout_seconds)
        if int(completed.returncode) != 0:
            evidence = _evidence(completed) or "no stderr"
            raise MissionScratchUnavailableError(
                "mission_scratch_unavailable: could not prepare the "
                f"owner-only secret-staging directory {path} on the Test "
                f"Machine ({' '.join(argv)} exited "
                f"{int(completed.returncode)}: {evidence}). The mission "
                "must not stage secrets without it: restore write access "
                "to the scratch root on the host, or free that path, then "
                "re-run the mission."
            )
    previous = None
    completed = _claim_owner_marker(
        control, execution_id, continues_execution_id, timeout_seconds
    )
    if int(completed.returncode) == _OWNER_CONFLICT_EXIT:
        previous = _replace_finished_owner(
            control,
            owner=json.loads(completed.stdout)["conflict"],
            owner_state=owner_state,
            timeout_seconds=timeout_seconds,
        )
        completed = _claim_owner_marker(
            control, execution_id, continues_execution_id, timeout_seconds
        )
    if int(completed.returncode) != 0:
        raise MissionScratchUnavailableError(
            "qa_project_owner_unavailable: could not mark this leased host's test "
            "projects; resolve the existing case owner or host write access and "
            "re-prepare the mission. " + _evidence(completed)
        )
    claimed = json.loads(completed.stdout)
    return {
        "scratch_path": path,
        "owner_marker": {
            "owner": execution_id,
            "previous_owner": claimed["previous_owner"],
            "inherited_owners": claimed["inherited_owners"],
            "replaced_finished_owner": previous,
        },
    }


# Exit status the host script uses for "another execution owns this host".
_OWNER_CONFLICT_EXIT = 3

# Runs on the leased host: claim the owner marker for argv[1]. A marker held
# by the continued execution (argv[2]) is inherited, so its projects retire
# with this mission; any other owner refuses with _OWNER_CONFLICT_EXIT.
_CLAIM_OWNER_SCRIPT = (
    "import json,sys; from pathlib import Path; "
    f"p=Path.home()/'.yoke'/{OWNER_FILE!r}; "
    "p.parent.mkdir(parents=True,exist_ok=True); "
    "previous=json.loads(p.read_text()) if p.exists() else {}; "
    "owner=previous.get('owner'); "
    "inherited=list(previous.get('inherited_owners') or []); "
    "conflict=owner and owner!=sys.argv[1] and owner not in sys.argv[2:]; "
    "conflict and (print(json.dumps({'conflict':owner})), sys.exit(3)); "
    "inherited+=[owner] if owner and owner!=sys.argv[1] else []; "
    "p.write_text(json.dumps({'owner':sys.argv[1],'inherited_owners':inherited})); "
    "p.chmod(0o600); "
    "print(json.dumps({'previous_owner':owner,'inherited_owners':inherited}))"
)


def _claim_owner_marker(
    control: MissionScratchHostControl,
    execution_id: str,
    continues_execution_id: str | None,
    timeout_seconds: int,
) -> Any:
    argv = ["python3", "-c", _CLAIM_OWNER_SCRIPT, execution_id]
    if continues_execution_id:
        argv.append(continues_execution_id)
    return control.run_command(argv, timeout=timeout_seconds)


def _replace_finished_owner(
    control: MissionScratchHostControl,
    *,
    owner: str,
    owner_state: OwnerStateLookup | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Tear down a terminal execution's leftovers; refuse a live owner."""
    if owner_state is None:
        raise MissionScratchUnavailableError(
            f"qa_project_owner_conflict: execution {owner} still marks this "
            "leased host's test projects and this caller cannot ask the "
            "control plane whether it finished; run the mission through "
            "`yoke qa plan run` so preparation can confirm the owner is "
            "terminal before replacing its marker."
        )
    state = owner_state(owner)
    if not state.get("terminal"):
        raise MissionScratchUnavailableError(
            f"qa_project_owner_conflict: execution {owner} owns this leased "
            f"host's test projects and is {state.get('state') or 'unknown'} in "
            "the control plane; use its lease and do not remove its ownership "
            "marker. Wait for that execution to finish, or abort it, then "
            "re-run this mission."
        )
    teardown = remove_mission_scratch(
        control, execution_id=owner, timeout_seconds=timeout_seconds
    )
    if not teardown["project_cleanup_ok"] or not teardown["removed"]:
        raise MissionScratchUnavailableError(
            f"qa_project_owner_replacement_failed: execution {owner} is "
            f"{state['state']} but its leftovers on this host did not tear "
            f"down ({teardown['project_cleanup']}; scratch removed="
            f"{teardown['removed']}). Resolve the named blocker on the host, "
            "then re-run this mission."
        )
    return {"execution_id": owner, "state": state["state"], "teardown": teardown}


def remove_mission_scratch(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Remove the lease's staging directory and prove it is gone."""
    path = mission_scratch_path(execution_id)
    # The fresh host need not have installed the product yet. Stage the
    # stdlib-only helper as code, using the same implementation tests import.
    script = Path(__file__).with_name("machine_qa_project_cleanup.py").read_text()
    cleanup = control.run_command(
        ["python3", "-c", script, execution_id, OWNER_FILE, OWNER_CAPABILITY],
        timeout=timeout_seconds,
    )
    removal = control.run_command(
        mission_scratch_remove_argv(path),
        timeout=timeout_seconds,
    )
    probe = control.run_command(
        mission_scratch_probe_argv(path),
        timeout=timeout_seconds,
    )
    return {
        "scratch_path": path,
        "removed": int(probe.returncode) != 0,
        "removal_exit_code": int(removal.returncode),
        "removal_stderr": _evidence(removal),
        "project_cleanup_ok": int(cleanup.returncode) == 0,
        "project_cleanup": (
            json.loads(cleanup.stdout)
            if int(cleanup.returncode) == 0
            else {
                "error": _evidence(cleanup),
                "recovery": "Resolve the retirement blocker and retry mission scratch-teardown",
            }
        ),
    }


__all__ = [
    "MissionScratchHostControl",
    "MissionScratchUnavailableError",
    "OwnerStateLookup",
    "create_mission_scratch",
    "remove_mission_scratch",
]
