"""Keep a live interactive conversation with the process that holds it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from yoke_contracts import platform_process
from yoke_cli.config import machine_config
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness import session_launch_handles
from yoke_harness.session_launch_containment import supervised_records
from yoke_harness.session_relay_process_liveness import PROCESS_ANCHOR_SOURCE
from yoke_harness.session_relay_termination import read_local_record

if TYPE_CHECKING:
    from yoke_harness.session_relay_native_turn_custody import RunningNative
    from yoke_harness.session_relay_runtime import RelayExecutionContext


def _owned_processes(state_dir: Path | None) -> set[tuple[int, str]]:
    records = [record for _, record in supervised_records(state_dir)]
    for path in session_launch_handles.native_handle_directory().glob("*.json"):
        record = read_local_record(path)
        if record is not None:
            records.append(record)
    return {
        (int(pid), str(started))
        for record in records
        for pid, started in dict(record.get("process_members") or {}).items()
    } | {
        (record["pid"], record["process_start_time"])
        for record in records
        if isinstance(record.get("pid"), int) and record.get("process_start_time")
    }



def running_interactive_holder(
    session_id: str,
    *,
    native_thread_id: str | None = None,
    custody_state_dir: Path | None = None,
    anchors_dir: Path | None = None,
    start_time_of: Callable[[int], str | None] | None = None,
) -> RunningNative | None:
    """Find a live anchor outside relay custody, including contended anchors.

    Start-time equality excludes dead and reused pids. Exclude recorded descendants
    and live supervisor ancestry belonging to relay custody.
    The message remains pending for the holder's next hook, even between turns.
    """
    from yoke_harness.session_relay_native_turn_custody import RunningNative

    wanted = {
        value
        for value in (
            session_id,
            native_thread_id,
        )
        if value
    }
    if not wanted:
        return None
    start_time_of = start_time_of or process_start_time
    owned_processes = _owned_processes(custody_state_dir)
    directory = anchors_dir or machine_config.yoke_home() / ANCHORS_DIR_NAME
    for path in sorted(directory.glob("*.json")):
        record = read_local_record(path)
        if record is None:
            continue
        contenders = record.get("contending_session_ids")
        identities = {record.get("session_id")}
        if isinstance(contenders, list):
            identities.update(value for value in contenders if isinstance(value, str))
        if not wanted.intersection(identities):
            continue
        pid, started = record.get("anchor_pid"), record.get("anchor_start_time")
        if not isinstance(pid, int) or pid <= 0 or not started:
            continue
        if start_time_of(pid) != started:
            continue
        if (pid, str(started)) in owned_processes:
            continue
        ancestry = platform_process.ancestors(pid)
        if any((entry.pid, str(entry.start_time)) in owned_processes
               for entry in ancestry):
            continue
        return RunningNative(
            session_id,
            pid,
            str(started),
            PROCESS_ANCHOR_SOURCE,
        )
    return None


def interactive_holder(
    context: RelayExecutionContext,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: Callable[[int], str | None] | None = None,
) -> RunningNative | None:
    """Resolve the holder using a pending wake's session and native identity."""
    return running_interactive_holder(
        context.target_session_id or "",
        native_thread_id=context.target_native_thread_id,
        custody_state_dir=custody_state_dir,
        start_time_of=start_time_of,
    )
