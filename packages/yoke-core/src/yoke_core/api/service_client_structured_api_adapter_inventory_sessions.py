"""Session and charge adapter inventory rows."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


SESSION_ADAPTERS = [
    AdapterEntry(
        function_id="sessions.watcher_activity",
        cli_invocation="yoke sessions watcher-activity [--json]",
    ),
    AdapterEntry(
        function_id="sessions.begin",
        cli_invocation=(
            "yoke sessions begin --executor E --provider P --requested-model M --workspace W [--project ID] [--mode MODE] [--entrypoint E] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="sessions.identity",
        cli_invocation=("yoke sessions identity [--full] [--session-id S] [--json]"),
    ),
    AdapterEntry(
        function_id="sessions.touch",
        cli_invocation=(
            "yoke sessions touch [--mode MODE] [--reason TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="sessions.checkpoint",
        cli_invocation=(
            "yoke sessions checkpoint --step N --action ACTION --chainable BOOL [--item PREFIX-N] [--task-num N] [--outcome O] [--status S] [--required-path P] [--pre-status PS] [--failure-class C] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="sessions.checkpoint_read",
        cli_invocation=(
            "yoke sessions checkpoint-read [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="sessions.end_if_empty",
        cli_invocation=(
            "yoke sessions end-if-empty [--triggered-by SOURCE] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="sessions.reclaim_stale",
        cli_invocation=(
            "yoke sessions reclaim-stale --confirm [--project-ids ID,ID,...] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="sessions.list",
        cli_invocation=(
            "yoke sessions list [--project P] [--liveness active|waiting|stale|ended] [--ended-cause killed|wound_down] [--limit N] [--offset N] [--full] [--session SESSION-ID] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="sessions.steering_groups.list",
        cli_invocation=("yoke sessions steering-groups list [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="sessions.hook_overhead",
        cli_invocation=(
            "yoke sessions hook-overhead [--hours N] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.evidence.get",
        cli_invocation=(
            "yoke session-control evidence get --session SESSION-ID [--kind relay|watcher|diagnostic] [--file NAME] [--evidence-id ND-REF] [--tail N] [--wait-seconds N] [--session-id S] [--json]"
        ),
        notes=(
            "records the request the owning machine's relay answers, so it "
            "writes a row rather than reading one"
        ),
    ),
    AdapterEntry(
        function_id="session_control.keepalive.hold",
        cli_invocation=(
            "yoke sessions keepalive hold SESSION-ID --reason R [--seconds N] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.keepalive.release",
        cli_invocation=(
            "yoke sessions keepalive release SESSION-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.session.terminate",
        cli_invocation=(
            "yoke sessions terminate SESSION-ID --reason TEXT [--allow-resume-in-flight] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.session.wake",
        cli_invocation=(
            "yoke session-control session wake (SESSION-ID | --item PREFIX-N) [--prompt TEXT] [--idempotency-key KEY] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.qualification.open",
        cli_invocation=(
            "yoke session-control qualification open --project P --release-sha SHA --run-id RUN --surface SURFACE --version V --operation OP --route (direct | broker | hook) [--session-id S] [--json]"
        ),
        notes="stage-only exact-release private-route proof",
        agent_path="direct",
    ),
    _read_entry(
        function_id="session_control.message.preview",
        cli_invocation=(
            "yoke session-control message preview (--item PREFIX-N | --actor ACTOR | --epic-task ITEM:N | --process KEY | --project P | --session S | --universe | --steering | --steering-scope JSON) [--executor FAMILY] [--surface SURFACE] [--role ROLE] [--execution-level LEVEL] [--worktree LANE] [--machine MACHINE] [--liveness active|waiting|stale|ended|all] [--exclude-session S] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.message.send",
        cli_invocation=(
            "yoke session-control message send --stdin (--item PREFIX-N | --actor ACTOR | --epic-task ITEM:N | --process KEY | --project P | --session S | --universe | --steering | --steering-scope JSON) [--executor FAMILY] [--surface SURFACE] [--role ROLE] [--execution-level LEVEL] [--worktree LANE] [--machine MACHINE] [--liveness active|waiting|stale|ended|all] [--exclude-session S] [--idempotency-key K] [--confirmation-token T] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.message.list",
        cli_invocation=(
            "yoke messages list [--state STATE] [--recipient-session S] [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.message.get",
        cli_invocation=(
            "yoke messages get MESSAGE-ID [FIELD ...] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.message.acknowledge",
        cli_invocation=(
            "yoke messages acknowledge MESSAGE-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.message.cancel",
        cli_invocation=("yoke messages cancel MESSAGE-ID [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="session_control.launch.preview",
        cli_invocation=(
            "yoke session-control launch preview --project P [--item PREFIX-N] [(--level LEVEL | --surface SURFACE [--model MODEL] [--reasoning-effort EFFORT] [--context-window TOKENS] [--allow-surface-fallback]) [--machine MACHINE_ID]] [--list-models] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.create",
        cli_invocation=(
            "yoke session-control launch create --project P [(--level LEVEL | --surface SURFACE [--model MODEL] [--reasoning-effort EFFORT] [--context-window TOKENS] [--allow-surface-fallback]) [--machine MACHINE_ID]] (--item PREFIX-N [--level-reason TEXT] | --raw-instructions --stdin) --idempotency-key K [--presentation MODE] [--list-models] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.launch.get",
        cli_invocation=(
            "yoke session-control launch get LAUNCH-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.launch.list",
        cli_invocation=(
            "yoke session-control launch list --project P [--state STATE] [--surface SURFACE] [--machine MACHINE] [--item PREFIX-N] [--limit N] [--cursor CURSOR] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.cancel",
        cli_invocation=(
            "yoke session-control launch cancel LAUNCH-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.retry",
        cli_invocation=(
            "yoke session-control launch retry LAUNCH-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.launch.reconcile",
        cli_invocation=(
            "yoke session-control launch reconcile LAUNCH-ID [--observed-native-id ID] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.surface_policy.disable",
        cli_invocation=(
            "yoke session-control surface-policy disable --project P --machine M --surface SURFACE --reason TEXT [--evidence TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="session_control.surface_policy.enable",
        cli_invocation=(
            "yoke session-control surface-policy enable --project P --machine M --surface SURFACE [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="session_control.surface_policy.list",
        cli_invocation=(
            "yoke session-control surface-policy list [--machine M] [--surface SURFACE] [--include-cleared] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="charge.schedule",
        cli_invocation=(
            "yoke charge schedule [--project P] [--item PREFIX-N] [--workspace W] [--wip-cap N] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="frontier.list",
        cli_invocation=(
            "yoke frontier list [--project P] [--wip-cap N] [--full] [--session-id S] [--json]"
        ),
        notes=(
            "The schedule as a pure read: ranked ready rows with engine-owned "
            "ranks and blocked rows naming their gate points; emits no events."
        ),
    ),
]


__all__ = ["SESSION_ADAPTERS"]
