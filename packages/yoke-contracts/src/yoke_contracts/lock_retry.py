"""Transport-neutral lock refusals that can replay the same request."""

RETRYABLE_LOCK_CODES = frozenset({
    "run_busy", "qa_plan_busy", "idempotency_request_in_flight",
    "lock_timeout", "statement_cancelled",
})
