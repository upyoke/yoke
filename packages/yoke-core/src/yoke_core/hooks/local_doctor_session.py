"""Give native Full Access Doctor's registration hook its local authority."""

from __future__ import annotations

import os
from typing import Any, Callable

from yoke_contracts.harness_shell_tools import payload_shell_kind
from yoke_contracts.harness_unattended_posture import codex_posture_problems
from yoke_contracts.hook_budget import hook_budget_ms
from yoke_contracts.hook_runner.command_extract import raw_command
from yoke_contracts.hook_runner.shell_parse import parse_for_shell
from yoke_contracts.hook_tool_names import canonicalize_shell_payload


def prepare_local_doctor_session(
    event_name: str,
    executor: str,
    payload: dict[str, Any],
    *,
    read_posture: Callable[..., tuple[dict | None, str]],
) -> None:
    """Open a stopped embedded cluster before live hook registration.

    The caller is the local authority's hook evaluator. This does not
    register a session itself: the normal hook applies custody and stale
    replay checks to the original native event.
    """
    if event_name != "PreToolUse" or executor != "codex":
        return
    native = dict(payload)
    canonicalize_shell_payload(native)
    if native.get("tool_name") != "Bash" or not native.get("transcript_path"):
        return
    shell = parse_for_shell(raw_command(native), payload_shell_kind(native))
    if not shell.segments:
        return
    command = shell.segments[0]
    if (
        command.argv[:2] != ("yoke", "doctor")
        or command.assignments
        or {"-h", "--help"}.intersection(command.argv[2:])
    ):
        return
    session_id = native.get("session_id")
    turn_id = native.get("turn_id") or ""
    tool_use_id = native.get("tool_use_id") or ""
    if not all(isinstance(value, str) for value in (session_id, turn_id, tool_use_id)):
        return
    if not (session_id and (turn_id or tool_use_id)):
        return

    facts, _ = read_posture(
        session_id, turn_id=turn_id, tool_use_id=tool_use_id
    )
    if facts is None or codex_posture_problems(facts):
        return
    # Leave time for the registration and guard chain after the start attempt.
    timeout_s = min(3, hook_budget_ms(os.environ) // 1000 - 2)
    if timeout_s < 1:
        return
    _start_owned_cluster(timeout_s)


def _start_owned_cluster(timeout_s: int) -> None:
    from yoke_core.domain import (
        db_backend,
        local_universe,
        local_universe_convergence,
        postgres_binaries,
        postgres_cluster,
        universe_source_pause,
    )

    try:
        dsn = db_backend.resolve_pg_dsn()
        if not local_universe_convergence.serves_own_universe(dsn):
            return
        universe_source_pause.require_running(dsn)
        bin_dir = postgres_binaries.installed_bin_dir()
        spec = local_universe.cluster_spec(bin_dir=bin_dir)
        if bin_dir is None or not (spec.data_dir / "PG_VERSION").is_file():
            return
        # The hook only starts an existing local cluster. The command retains
        # its normal bootstrap and error reporting if this attempt fails.
        postgres_cluster.start_failure(spec, timeout_s=timeout_s)
    except (LookupError, OSError, RuntimeError, ValueError):
        return
