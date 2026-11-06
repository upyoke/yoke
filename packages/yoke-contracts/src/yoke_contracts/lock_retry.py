"""Transport-neutral lock refusals that can replay the same request."""

RETRYABLE_LOCK_CODES = frozenset({
    "run_busy", "qa_plan_busy", "idempotency_request_in_flight",
    "lock_timeout", "statement_cancelled",
    "qa_checkin_busy", "qa_ownership_busy",
    "deployment_start_lock_busy", "deployment_membership_changed",
})
