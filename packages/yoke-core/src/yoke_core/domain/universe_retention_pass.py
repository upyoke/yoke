"""One time-bounded prune pass over the fixed cleanup rules.

A pass walks the rules from ``table_index``. On apply it repeats cohorts on
a table while more eligible rows remain and the last cohort deleted rows.
Reaching the pass deadline is never a failure: the pass returns and the next
one resumes the same table. A statement or lock limit hit by the pass's first
cohort (full budget) skips that table for this pass; the caller decides how
often to retry it.
"""

from __future__ import annotations

import time

from yoke_contracts.timestamps import as_utc, utc_now
from yoke_core.domain.universe_retention import _table_pass, read_retention

LIMIT_SQLSTATES = ("57014", "55P03")
POLICY_ERRORS = ("retention_policy_changed:", "retention_policy_invalid:")


def rules_for(policy, cutoff):
    from yoke_core.domain.retention_message_graphs import policies as graph_policies
    from yoke_core.domain.retention_operational_policy import upload_policy
    from yoke_core.domain.retention_table_policies import policies
    from yoke_core.domain.universe_retention_snapshots import snapshot_policy

    return (
        policies(policy, cutoff)
        + graph_policies(policy, cutoff)
        + [snapshot_policy(), upload_policy(policy, cutoff)]
    )


def _hit_limit(exc):
    return isinstance(exc, TimeoutError) or getattr(exc, "sqlstate", "") in (
        LIMIT_SQLSTATES
    )


def _table_failure(rule, exc):
    if isinstance(exc, ValueError) and str(exc).startswith(POLICY_ERRORS):
        return {
            "code": str(exc).partition(":")[0],
            "table": rule.table,
            "reason": str(exc),
            "recovery": "Earlier committed batches remain committed. Review universe retention get, then rerun universe prune.",
        }
    code = getattr(exc, "sqlstate", "") or type(exc).__name__
    return {
        "code": "retention_table_failed",
        "table": rule.table,
        "reason": f"database operation refused ({code}); no uncommitted cohort was applied",
        "recovery": "Earlier committed batches remain committed. Restore the database condition and rerun universe prune; if it repeats, ask the universe administrator to inspect this table.",
    }


def _skipped(rule):
    return {
        "table": rule.table,
        "code": "retention_table_limit",
        "reason": "a statement or lock limit was reached with the full pass budget",
        "recovery": "Other tables continued. Rerun universe prune when the table is quieter; if it repeats, ask the universe administrator to inspect this table's indexes and locks.",
    }


def prune_pass(conn, request):
    current = utc_now()
    cutoff = as_utc(request.cutoff) if request.cutoff else current
    if cutoff > current:
        raise ValueError(
            "retention_cutoff_in_future: recovery: rerun the command with the server's current UTC cutoff."
        )
    policy, result = read_retention(conn, cutoff)
    if request.expected_digest and request.expected_digest != policy.digest:
        raise ValueError(
            "retention_policy_changed: recovery: review universe retention get, then rerun prune with its new policy."
        )
    rules = rules_for(policy, cutoff)
    unknown = set(request.skip_tables) - {rule.table for rule in rules}
    if request.table_index >= len(rules) or unknown:
        raise ValueError(
            "retention_table_index_invalid: recovery: rerun universe prune from the beginning."
        )
    # End read transactions before the cohort's bounded custody starts.
    conn.rollback()
    deadline = time.monotonic() + policy.pass_seconds
    result.update(
        tables=[],
        skipped=[],
        next_table_index=request.table_index,
        cycle_complete=False,
        failure=None,
    )
    full_budget = True
    index = request.table_index
    while index < len(rules):
        rule = rules[index]
        result["next_table_index"] = index
        if rule.table in request.skip_tables:
            index += 1
            continue
        if time.monotonic() >= deadline:
            return result
        try:
            row = _table_pass(conn, policy, deadline, rule, request.apply)
        except Exception as exc:
            conn.rollback()
            if not _hit_limit(exc):
                result["failure"] = _table_failure(rule, exc)
                return result
            if not full_budget:
                # The deadline clipped this cohort: resume here next pass.
                return result
            result["skipped"].append(_skipped(rule))
            full_budget = False
            index += 1
            continue
        full_budget = False
        result["tables"].append(row)
        repeat = (
            request.apply and row["eligible_partial"] and any(row["deleted"].values())
        )
        if not repeat:
            index += 1
    result["next_table_index"] = 0
    result["cycle_complete"] = True
    return result
