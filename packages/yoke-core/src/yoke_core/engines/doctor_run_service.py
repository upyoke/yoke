"""Execute and collect the Doctor checks selected by a service request."""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def run(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_selection import missing_project_on_connection
    from yoke_core.domain.handlers.doctor_run_scope import (
        doctor_scope_label,
        project_safe_quick_checks,
        validate_only_slugs,
    )
    from yoke_core.domain.last_doctor_run_read import persist_completed_run
    from yoke_core.engines.doctor_context import resolve_context
    from yoke_core.engines.doctor_check_execution import execute_check_isolated
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS
    from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
    from yoke_core.engines.doctor_roster import (
        build_roster,
        record_discovery_failures,
        record_not_applicable,
        record_roster_collisions,
    )

    payload = request.payload or {}
    only_raw = payload.get("only")
    quick = bool(payload.get("quick", False))
    full = bool(payload.get("full", False))
    cursor_after_raw = payload.get("cursor_after")
    max_checks_raw = payload.get("max_checks")

    # Exactly one of quick / full / only must be supplied — defends against
    # JSON callers silently running the full GitHub-dependent suite.
    scope_flags = [bool(quick), bool(full), bool(only_raw)]
    if sum(scope_flags) != 1:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="scope_required",
                message=(
                    "doctor.run.run requires exactly one scope: "
                    "quick=true, full=true, or only=<slug,slug...>. "
                    "The explicit-scope rule prevents silent gh-quota burn."
                ),
                jsonpath="$.payload",
            ),
        )

    if only_raw is not None and not isinstance(only_raw, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="only must be a comma-separated string of slugs",
                jsonpath="$.payload.only",
            ),
        )

    if cursor_after_raw is not None and not isinstance(cursor_after_raw, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="cursor_after must be a health-check slug",
                jsonpath="$.payload.cursor_after",
            ),
        )
    max_checks = None
    if max_checks_raw is not None:
        try:
            max_checks = int(max_checks_raw)
        except (TypeError, ValueError):
            max_checks = 0
        if max_checks <= 0:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="max_checks must be a positive integer",
                    jsonpath="$.payload.max_checks",
                ),
            )

    db_path = payload.get("db_path")
    args = DoctorArgs(
        only=only_raw,
        quick=quick,
        project=payload.get("project"),
        fix=bool(payload.get("fix", False)),
        db_path=str(db_path) if db_path else None,
        runtime=payload.get("runtime"),
    )
    rec = RecordCollector()
    conn = connect(path=args.db_path)
    if not str(args.project or "").strip():
        try:
            message = missing_project_on_connection(
                conn, actor_id=request.actor.actor_id
            )
        finally:
            conn.close()
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_required",
                message=message,
            ),
        )
    context = resolve_context(conn, args)
    roster = build_roster(HEALTH_CHECKS, args, context)
    if only_raw:
        unknown = validate_only_slugs(only_raw, roster.known_slugs)
        if unknown:
            conn.close()
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="invalid_check",
                    message=(
                        "unknown HC slug(s): "
                        + ", ".join(unknown)
                        + ". Use only slugs registered for the target "
                        "project. List engine slugs via `python3 -m "
                        "yoke_core.engines.doctor --list-checks`; "
                        "project-local slugs are declared in the target "
                        "checkout's `.yoke/doctor/` folder."
                    ),
                    jsonpath="$.payload.only",
                ),
            )
    selected = roster.applicable
    if bool(payload.get("project_safe_quick")) and not context.targets_self_project:
        selected = project_safe_quick_checks(selected)
    # Not-applicable results and discovery failures belong to the first
    # chunk: a paginating caller must see them exactly once, and they are
    # already known before any check runs.
    if not cursor_after_raw:
        record_discovery_failures(roster, rec)
        record_roster_collisions(roster, rec)
        record_not_applicable(roster, rec)
    start_index = 0
    cursor_after = (cursor_after_raw or "").strip()
    if cursor_after:
        selected_slugs = [hc.slug for hc in selected]
        try:
            start_index = selected_slugs.index(cursor_after) + 1
        except ValueError:
            conn.close()
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="invalid_cursor",
                    message=(
                        f"cursor_after does not match this doctor scope: {cursor_after}"
                    ),
                    jsonpath="$.payload.cursor_after",
                ),
            )
    ran_count = 0
    last_cursor = cursor_after or None
    served: Dict[str, Any]
    try:
        for hc in selected[start_index:]:
            if max_checks is not None and ran_count >= max_checks:
                break
            execute_check_isolated(conn, args, rec, hc)
            ran_count += 1
            last_cursor = hc.slug
        done = start_index + ran_count >= len(selected)
        served = {
            "results": [
                {
                    "hc": r.check_id,
                    "name": r.check_name,
                    "severity": r.result,
                    "detail": r.detail,
                }
                for r in rec.results
            ],
            "scope": doctor_scope_label(args),
            "project": args.project,
            "runtime": context.runtime,
            "fail_count": rec.fail_count,
            "warn_count": rec.warn_count,
            "pass_count": rec.pass_count,
            "na_count": rec.na_count,
            "done": done,
            "cursor": last_cursor,
        }
        if done and not cursor_after_raw:
            persist_completed_run(conn, served)
    finally:
        conn.close()
    return HandlerOutcome(result_payload=served, primary_success=True)
