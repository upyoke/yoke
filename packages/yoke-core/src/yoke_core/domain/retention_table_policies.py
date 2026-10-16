"""Explicit cleanup predicates for disposable universe tables."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Cleanup:
    table: str
    keys: tuple[str, ...]
    where: str
    params: tuple = ()
    children: tuple[tuple[str, str, str], ...] = ()
    locks: tuple[str, ...] = ()
    reason: str = "age, outcome and live-reference protections"


def policies(policy, cutoff):
    """Only these fixed rules may delete; unrelated/new tables are untouched."""

    def before(key):
        return cutoff - timedelta(days=policy.windows[key])

    overrides = list(policy.event_days)
    event_parts, event_values = [], []
    if overrides:
        marks = ",".join("%s" for _ in overrides)
        for name, days in policy.event_days.items():
            event_parts.append("(t.event_name=%s AND t.created_at<%s)")
            event_values.extend((name, cutoff - timedelta(days=days)))
        excluded = f"t.event_name NOT IN ({marks})"
    else:
        excluded = "TRUE"
    for severity, days in policy.severity_days.items():
        event_parts.append(f"({excluded} AND t.severity=%s AND t.created_at<%s)")
        event_values.extend((*overrides, severity, cutoff - timedelta(days=days)))
    event_where = "(" + " OR ".join(event_parts) + ")"
    # Unknown severities never become eligible, including name overrides.
    event_where += " AND t.severity IN ('DEBUG','INFO','WARN','ERROR','FATAL','STATUS')"
    # Hash reference membership so LIMIT can stop the primary-key scan early;
    # anti joins otherwise sort millions of events before returning a cohort.
    # event_id is NOT NULL; excluding nullable references preserves protection.
    for table in ("path_moves", "path_context_values", "path_integrity_repairs"):
        event_where += f" AND t.event_id NOT IN (SELECT r.recorded_event_id FROM {table} r WHERE r.recorded_event_id IS NOT NULL)"
    rules = [
        Cleanup(
            "events",
            ("id",),
            event_where,
            tuple(event_values),
            locks=("path_moves", "path_context_values", "path_integrity_repairs"),
            reason="unknown severity and durable event references are protected",
        )
    ]
    checks = "t.event_type IN ('verify','function_authorize')"
    success = "((t.event_type='verify' AND t.outcome='success') OR (t.event_type='function_authorize' AND t.outcome='allowed'))"
    rules += [
        Cleanup(
            "api_token_audit",
            ("id",),
            f"({success} AND t.created_at<%s) OR ({checks} AND NOT {success} AND t.created_at<%s) OR (NOT {checks} AND t.created_at<%s)",
            (
                before("token_check_success"),
                before("token_check_other"),
                before("token_lifecycle"),
            ),
        ),
        Cleanup(
            "function_call_ledger",
            ("request_id",),
            "t.created_at<%s AND NOT EXISTS (SELECT 1 FROM github_workflow_dispatch_intents d WHERE d.request_id=t.request_id AND d.state='pending')",
            (before("replay"),),
            locks=("github_workflow_dispatch_intents",),
        ),
        Cleanup(
            "github_workflow_dispatch_intents",
            ("request_id", "attempt"),
            "t.state IN ('completed','rejected') AND t.updated_at<%s",
            (before("dispatch_intents"),),
        ),
        Cleanup(
            "session_tool_calls",
            ("id",),
            "t.completed_at<%s AND NOT EXISTS (SELECT 1 FROM work_claims w WHERE w.session_id=t.session_id AND w.released_at IS NULL) "
            "AND EXISTS (SELECT 1 FROM harness_sessions s WHERE s.session_id=t.session_id AND s.ended_at IS NOT NULL)",
            (before("tool_calls"),),
            locks=("work_claims", "harness_sessions"),
            reason="incomplete calls and detail belonging to live sessions/claims are protected",
        ),
        Cleanup(
            "session_evidence_fetches",
            ("fetch_id",),
            "t.state IN ('succeeded','failed','expired') AND t.completed_at<%s AND (t.lease_id IS NULL OR t.lease_expires_at<%s)",
            (before("evidence_fetches"), cutoff),
        ),
        Cleanup(
            "session_termination_reaps",
            ("target_session_id",),
            "t.state='succeeded' AND t.completed_at<%s AND (t.lease_id IS NULL OR t.lease_expires_at<%s)",
            (before("settled_waits"), cutoff),
        ),
        Cleanup(
            "session_ci_run_waits",
            ("id",),
            "t.conclusion<>'' AND t.notified_at<%s",
            (before("settled_waits"),),
        ),
        Cleanup(
            "qa_host_waits",
            ("id",),
            "t.state IN ('granted','cancelled') AND t.settled_at<%s "
            "AND EXISTS (SELECT 1 FROM qa_plan_executions e WHERE e.id=t.qa_plan_execution_id AND e.state IN ('completed','aborted') AND e.completed_at<%s)",
            (before("settled_waits"), before("settled_waits")),
            locks=("qa_plan_executions",),
        ),
    ]
    expiry = before("expired_security")
    for table, keys in (
        ("browser_sign_in_links", ("selector",)),
        ("machine_authorization_codes", ("device_hash",)),
        ("web_sessions", ("id",)),
        ("frontend_attribution_redemptions", ("org_id", "nonce")),
        ("merge_locks", ("id",)),
    ):
        rules.append(Cleanup(table, keys, "t.expires_at<%s", (expiry,)))
    # Existing inline cleanup stays faster; this selects remaining old windows.
    rules += [
        Cleanup(
            "machine_authorization_rate_limits",
            ("client_key", "operation"),
            "t.window_start<%s",
            (int(expiry.timestamp()) - 60,),
        ),
        Cleanup(
            "frontend_event_rate_limits",
            ("client_key",),
            "t.window_start<%s",
            (expiry - timedelta(seconds=60),),
        ),
    ]
    return rules
