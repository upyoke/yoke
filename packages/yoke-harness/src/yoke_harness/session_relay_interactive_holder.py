"""Keep a live interactive conversation with the process that holds it."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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


def _owned_groups(state_dir: Path | None) -> set[int]:
    records = [record for _, record in supervised_records(state_dir)]
    for path in session_launch_handles.native_handle_directory().glob("*.json"):
        record = read_local_record(path)
        if record is not None:
            records.append(record)
    return {
        group for record in records
        if isinstance(group := record.get("process_group_id"), int) and group > 0
    }


def interactive_holder(
    context: RelayExecutionContext,
    *,
    custody_state_dir: Path | None = None,
    start_time_of: Callable[[int], str | None] | None = None,
) -> RunningNative | None:
    """Find a live anchor outside relay custody, including contended anchors.

    Start-time equality excludes dead and reused pids. Compare process groups,
    not supervisor pids: Claude and Cursor's native runs under a supervisor.
    The message remains pending for the holder's next hook, even between turns.
    """
    from yoke_harness.session_relay_native_turn_custody import RunningNative

    wanted = {value for value in (
        context.target_session_id, context.target_native_thread_id,
    ) if value}
    if not wanted:
        return None
    start_time_of = start_time_of or process_start_time
    owned_groups = _owned_groups(custody_state_dir)
    directory = machine_config.yoke_home() / ANCHORS_DIR_NAME
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
        try:
            group = os.getpgid(pid)
        except ProcessLookupError:
            continue
        except OSError:
            # A live identity without readable group ownership is still a holder.
            group = None
        if group in owned_groups:
            continue
        return RunningNative(
            context.target_session_id or "", pid, str(started), PROCESS_ANCHOR_SOURCE,
        )
    return None
