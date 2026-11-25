"""Report the outcome of a launch's creating process.

Two things are true at once for a launch whose native is gone: the machine
that started it knows within seconds, and the control plane knows nothing for
ten minutes. That gap is not a waiting period anyone chose — it is the
registration deadline doing its job for the case it was written for, a native
that is still coming up, applied to one that is already over. Four launches on
one afternoon each sat in ``registration_pending`` for the full ten minutes and
then closed with no captured output, while the answer had been on disk the
whole time.

The custody record is what makes this readable without a second registry:
the relay writes one for every native it starts and delivery removes it, so a
record that still exists names a launch whose instruction never reached a
registered session. A record whose capture records a fatal exit, or whose
recorded pid is no longer the recorded process, names the shape this reports
on every harness because every harness writes the same record and capture.

After registration the launch handle still names the creating process. Send
its measured exit even when a newer process keeps the session live. Only
the control plane decides whether the bound session or launch should close.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.process_ancestry import process_start_time
from yoke_harness.session_launch_handles import native_handle_directory
from yoke_harness.session_process_custody import custody_state, write_record
from yoke_harness.session_launch_containment import (
    release_supervised_native,
    supervised_records,
)
from yoke_harness.session_relay_liveness_batches import deliver_liveness_batches
from yoke_harness.session_relay_native_account import native_account
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS
from yoke_harness.session_relay_termination import read_local_record


Dispatcher = Callable[..., Any]
StartTimeOf = Callable[[int], str | None]


@dataclass(frozen=True)
class UnregisteredLaunchDeath:
    """One launch with a fatal result or a gone native before registration."""

    launch_id: str
    evidence: dict[str, Any]


def _captured_registered_exits(
    state_dir: Path | None,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Read finalized captures independently of the session's other processes."""
    ready: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(native_handle_directory().glob("*.json")):
        record = read_local_record(path)
        if not record or record.get("native_exit_reported"):
            continue
        launch_id = record.get("launch_id")
        session_id = record.get("target_session_id")
        pid = record.get("pid")
        if launch_id != path.stem or not session_id or type(pid) is not int or pid <= 0:
            continue
        account = native_account(launch_id, state_dir=state_dir)
        if account.get("native_exit_at"):
            ready[launch_id] = (
                path,
                {**account, "native_pid": pid, "registered_session_id": session_id},
            )
    return ready


def _mark_exit_reported(path: Path, launch_id: str, pid: int) -> None:
    record = read_local_record(path)
    if record and record.get("launch_id") == launch_id and record.get("pid") == pid:
        write_record(path, {**record, "native_exit_reported": True})


def unregistered_launch_deaths(
    *,
    state_dir: Path | None = None,
    diagnostic_state_dir: Path | None = None,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[UnregisteredLaunchDeath, ...]:
    """Return launches with a fatal capture or a verified gone native."""
    deaths: list[UnregisteredLaunchDeath] = []
    for _path, payload in supervised_records(state_dir):
        if str(payload.get("supervision_kind") or "launch") != "launch":
            continue
        launch_id = str(payload.get("launch_id") or "").strip()
        pid = payload.get("pid")
        if not launch_id or not isinstance(pid, int) or pid <= 0:
            continue
        account = native_account(
            launch_id,
            state_dir=diagnostic_state_dir or state_dir,
        )
        exit_code = account.get("exit_code")
        fatal_result = (
            isinstance(exit_code, int)
            and not isinstance(exit_code, bool)
            and exit_code != 0
            and bool(account.get("native_exit_at"))
        )
        # A finalized fatal capture is authoritative even if the supervisor
        # process has not disappeared yet. Otherwise require proof that its
        # recorded pid is gone (or has been reused).
        bound_exit = payload.get("target_session_id") and account.get("native_exit_at")
        if not bound_exit and not fatal_result and custody_state(payload) != "gone":
            continue
        deaths.append(
            UnregisteredLaunchDeath(
                launch_id,
                {
                    "native_pid": pid,
                    **account,
                },
            )
        )
    return tuple(deaths)


def report_unregistered_launch_deaths(
    dispatcher: Dispatcher,
    inventory: Any,
    *,
    state_dir: Path | None = None,
    custody_state_dir: Path | None = None,
    timeout_s: int = RELAY_REPORT_TIMEOUT_SECONDS,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[str, ...]:
    """Report this poll's creating-native exits and return those sent.

    Custody defaults to the machine cache shared with hooks and containment;
    ``state_dir`` selects this relay's diagnostic and report-retry storage.

    A bound launch's handle remains available to session liveness. Mark its
    measured exit reported only after the server confirms it was recorded.
    """
    deaths = unregistered_launch_deaths(
        state_dir=custody_state_dir,
        diagnostic_state_dir=state_dir,
        start_time_of=start_time_of,
    )
    registered = _captured_registered_exits(state_dir)
    reports = {death.launch_id: death.evidence for death in deaths}
    reports.update({launch_id: evidence for launch_id, (_, evidence) in registered.items()})
    if not reports:
        return ()
    reported: list[str] = []
    for batch, result in deliver_liveness_batches(
        dispatcher,
        inventory,
        collection="launches",
        reports=[
            {"launch_id": launch_id, "evidence": evidence}
            for launch_id, evidence in reports.items()
        ],
        timeout_s=timeout_s,
        refusal_label="relay launch-death report",
    ):
        recorded = set(result.get("recorded_native_exits") or [])
        pending_bound = {
            skipped.get("launch_id")
            for skipped in (result.get("skipped_launches") or [])
            if skipped.get("status") == "registered"
        }
        for report in batch:
            launch_id = str(report["launch_id"])
            if launch_id in registered and launch_id in recorded:
                path, evidence = registered[launch_id]
                _mark_exit_reported(path, launch_id, evidence["native_pid"])
            if launch_id not in pending_bound or not reports[launch_id].get("native_exit_at"):
                release_supervised_native(launch_id, state_dir=custody_state_dir)
            reported.append(launch_id)
    return tuple(reported)


__all__ = [
    "UnregisteredLaunchDeath",
    "report_unregistered_launch_deaths",
    "unregistered_launch_deaths",
]
