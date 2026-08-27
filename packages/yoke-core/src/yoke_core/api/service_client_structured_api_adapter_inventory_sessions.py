"""Session and charge adapter inventory rows."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


SESSION_ADAPTERS = [
    AdapterEntry(
        function_id="sessions.begin",
        cli_invocation=(
            "yoke sessions begin --executor E --provider P --model M --workspace W"
        ),
    ),
    _read_entry(
        function_id="sessions.identity",
        cli_invocation="yoke sessions identity",
    ),
    AdapterEntry(
        function_id="sessions.touch",
        cli_invocation="yoke sessions touch [--mode MODE]",
    ),
    AdapterEntry(
        function_id="sessions.checkpoint",
        cli_invocation=(
            "yoke sessions checkpoint --step N --action ACTION --chainable BOOL"
        ),
    ),
    _read_entry(
        function_id="sessions.checkpoint_read",
        cli_invocation="yoke sessions checkpoint-read",
    ),
    AdapterEntry(
        function_id="sessions.offer",
        cli_invocation=("yoke sessions offer [--step N] [--project IDS]"),
    ),
    AdapterEntry(
        function_id="sessions.end_if_empty",
        cli_invocation="yoke sessions end-if-empty [--triggered-by SOURCE]",
    ),
    AdapterEntry(
        function_id="sessions.reclaim_stale",
        cli_invocation=(
            "yoke sessions reclaim-stale --confirm [--project-ids ID,ID,...]"
        ),
    ),
    _read_entry(
        function_id="sessions.list",
        cli_invocation=(
            "yoke sessions list [--project P] "
            "[--liveness active|stale|ended] [--ended-cause killed|wound_down] "
            "[--limit N] [--session S]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.session.terminate",
        cli_invocation=(
            "yoke sessions terminate SESSION-ID --reason R "
            "[--override-chain-end --chain-end-rationale R]"
        ),
    ),
    _read_entry(
        function_id="sessions.ownership_guard",
        cli_invocation="yoke sessions ownership-guard --item YOK-N",
    ),
    AdapterEntry(
        function_id="session_control.qualification.open",
        cli_invocation=(
            "yoke session-control qualification open --project P "
            "--release-sha SHA --run-id RUN --surface S --version V "
            "--operation OP --route ROUTE [--json]"
        ),
        notes="stage-only exact-release private-route proof",
        agent_path="operator-only",
    ),
    _read_entry(
        function_id="session_control.message.preview",
        cli_invocation="yoke session-control message preview [selector] [--json]",
    ),
    AdapterEntry(
        function_id="session_control.message.send",
        cli_invocation=(
            "yoke session-control message send --stdin [selector] "
            "[--idempotency-key K] [--confirmation-token T] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.message.list",
        cli_invocation=(
            "yoke messages list [--state STATE] [--recipient-session S] "
            "[--limit N] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.message.get",
        cli_invocation="yoke messages get MESSAGE-ID [--json]",
    ),
    AdapterEntry(
        function_id="session_control.message.acknowledge",
        cli_invocation="yoke messages acknowledge MESSAGE-ID [--json]",
    ),
    AdapterEntry(
        function_id="session_control.message.cancel",
        cli_invocation="yoke messages cancel MESSAGE-ID [--json]",
    ),
    _read_entry(
        function_id="session_control.launch.preview",
        cli_invocation=(
            "yoke session-control launch preview --project P --surface S [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.create",
        cli_invocation=(
            "yoke session-control launch create --project P --surface S "
            "--stdin --idempotency-key K [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.launch.get",
        cli_invocation="yoke session-control launch get LAUNCH-ID [--json]",
    ),
    _read_entry(
        function_id="session_control.launch.list",
        cli_invocation=(
            "yoke session-control launch list --project P "
            "[--state STATE] [--limit N] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.cancel",
        cli_invocation="yoke session-control launch cancel LAUNCH-ID [--json]",
    ),
    AdapterEntry(
        function_id="session_control.launch.retry",
        cli_invocation="yoke session-control launch retry LAUNCH-ID [--json]",
    ),
    AdapterEntry(
        function_id="session_control.launch.reconcile",
        cli_invocation=(
            "yoke session-control launch reconcile LAUNCH-ID "
            "[--observed-native-id ID] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="charge.schedule",
        cli_invocation="yoke charge schedule [--project P] [--item PREFIX-N] [--workspace W] [--wip-cap N]",
    ),
    _read_entry(
        function_id="frontier.list",
        cli_invocation="yoke frontier list [--project P] [--wip-cap N]",
        notes=(
            "The schedule as a pure read: ranked ready rows with engine-owned "
            "ranks and blocked rows naming their gate points; emits no events."
        ),
    ),
]


__all__ = ["SESSION_ADAPTERS"]
